from __future__ import annotations

import logging
import time
from typing import Any, Optional

from pumpfun_trading.api.client import PumpFunApiClient
from pumpfun_trading.bot.strategy import (
    DevWalletProfile,
    HolderDistribution,
    ScreeningCache,
    TokenMetadata,
    TokenScreeningVerdict,
    TradingStrategy,
)
from pumpfun_trading.sdk.execution import PumpFunExecutionClient
from pumpfun_trading.strategies.base import TradingBotConfig

logger = logging.getLogger(__name__)


class TokenEnricher:
    """Handles off-chain token metadata enrichment, creator profiling, and anti-rug screening."""

    def __init__(
        self,
        api_client: Optional[PumpFunApiClient] = None,
        execution_client: Optional[PumpFunExecutionClient] = None,
        config: Optional[TradingBotConfig] = None,
        strategy: Optional[TradingStrategy] = None,
        screening_cache: Optional[ScreeningCache] = None,
    ) -> None:
        self.api = api_client
        self.execution = execution_client
        self.config = config or TradingBotConfig()
        self.strategy = strategy or TradingStrategy(self.config)
        self.screening_cache = screening_cache or ScreeningCache(
            default_ttl=float(self.config.screening_cache_ttl_seconds)
        )

    async def enrich_and_screen(
        self,
        mint: str,
        token_data: Optional[dict[str, Any]] = None,
        config: Optional[TradingBotConfig] = None,
    ) -> TokenScreeningVerdict:
        """Enriches off-chain metadata, developer profile, and top holders, evaluating anti-rug heuristics."""
        active_config = config or self.config
        if not active_config.enable_anti_rug_filters:
            return TokenScreeningVerdict(
                mint=mint,
                passed=True,
                risk_score=0.0,
                reasons=["Anti-rug filters disabled in strategy configuration."],
            )

        cached_verdict = self.screening_cache.get(mint)
        if cached_verdict is not None:
            return cached_verdict

        coin_data: dict[str, Any] = dict(token_data or {})
        if not coin_data and self.api:
            try:
                fetched = await self.api.get_coin(mint)
                if isinstance(fetched, dict):
                    coin_data = fetched
            except Exception as exc:
                logger.debug(
                    "Metadata query for %s failed during screening: %s", mint, exc
                )

        metadata = TokenMetadata.from_dict(coin_data) if coin_data else None

        dev_profile = None
        creator = (
            coin_data.get("creator")
            or coin_data.get("user")
            or coin_data.get("creatorAddress")
            or coin_data.get("dev_wallet")
        )
        if creator and isinstance(creator, str) and self.api:
            try:
                creator_coins = await self.api.get_creator_coins(creator, limit=20)
                if isinstance(creator_coins, list):
                    now_ms = time.time() * 1000
                    day_ago_ms = now_ms - (86400 * 1000)
                    count_24h = sum(
                        1
                        for c in creator_coins
                        if isinstance(c, dict)
                        and (
                            c.get("created_timestamp", 0) > day_ago_ms
                            or c.get("createdAt", 0) > day_ago_ms
                        )
                    )
                    dev_profile = DevWalletProfile(
                        creator_address=creator,
                        tokens_launched_24h=count_24h or len(creator_coins),
                        total_tokens_launched=len(creator_coins),
                    )
                elif isinstance(creator_coins, dict):
                    coins_list = (
                        creator_coins.get("coins") or creator_coins.get("items") or []
                    )
                    dev_profile = DevWalletProfile(
                        creator_address=creator,
                        tokens_launched_24h=len(coins_list),
                        total_tokens_launched=len(coins_list),
                    )
            except Exception as exc:
                logger.debug("Creator profile query for %s failed: %s", creator, exc)
                dev_profile = DevWalletProfile(creator_address=str(creator))
        elif creator and isinstance(creator, str):
            dev_profile = DevWalletProfile(creator_address=str(creator))

        bonding_curve_pda = None
        if self.execution:
            try:
                pda, _ = self.execution.get_bonding_curve_pda(mint)
                bonding_curve_pda = str(pda)
            except Exception:
                pass

        holder_distribution = None
        holders_data = coin_data.get("holders") or coin_data.get("topHolders")
        creator_holding_val = (
            coin_data.get("creatorHoldingPct")
            or coin_data.get("creator_holding_pct")
            or coin_data.get("creatorPct")
            or coin_data.get("dev_holding_pct")
        )
        creator_pct = (
            float(creator_holding_val) if creator_holding_val is not None else 0.0
        )

        if isinstance(holders_data, list):
            top_holders_list = []
            for h in holders_data:
                if isinstance(h, dict):
                    w = str(h.get("address") or h.get("wallet") or "")
                    amt = int(h.get("amount") or h.get("balance") or 0)
                    if w:
                        top_holders_list.append((w, amt))
            total_supply = int(
                coin_data.get("totalSupply")
                or coin_data.get("total_supply")
                or 1_000_000_000_000_000
            )
            holder_distribution = HolderDistribution(
                total_supply=total_supply,
                creator_initial_pct=creator_pct,
                bonding_curve_address=bonding_curve_pda,
                top_holders=top_holders_list,
            )
        elif creator_holding_val is not None:
            holder_distribution = HolderDistribution(
                creator_initial_pct=creator_pct,
                bonding_curve_address=bonding_curve_pda,
            )

        verdict = self.strategy.screen_token(
            mint,
            metadata=metadata,
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            bonding_curve_pda=bonding_curve_pda,
            cache=self.screening_cache,
            use_cache=True,
        )

        if verdict.passed:
            logger.info(
                "Anti-rug screening PASSED for %s | risk score: %.1f/100",
                mint,
                verdict.risk_score,
            )
        else:
            logger.warning(
                "Anti-rug screening REJECTED %s | risk score: %.1f/100 | reasons: %s",
                mint,
                verdict.risk_score,
                verdict.reasons,
            )

        return verdict
