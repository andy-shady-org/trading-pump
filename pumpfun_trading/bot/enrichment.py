from __future__ import annotations

import asyncio
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

# Per-lookup budget for screening I/O; screening runs inside the trade lock.
DEFAULT_LOOKUP_TIMEOUT_SECONDS = 2.5
# getTokenLargestAccounts answers [] for a new mint on some RPC nodes (BUG-107).
HOLDER_LOOKUP_ATTEMPTS = 4
# Pump.fun mints have a fixed 1B-token supply (6 decimals).
PUMP_TOTAL_SUPPLY_UI = 1_000_000_000.0
_SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
_TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def _timestamp_ms(value: Any) -> float:
    """Normalizes epoch seconds or milliseconds to milliseconds."""
    try:
        ts = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return ts * 1000.0 if 0 < ts < 1e12 else ts


def count_launches_last_24h(coins: list[Any], *, now: float | None = None) -> int:
    """Counts creator coins created in the last 24h (BUG-58)."""
    now_ms = (now if now is not None else time.time()) * 1000.0
    day_ago_ms = now_ms - 86_400_000.0
    count = 0
    for coin in coins:
        if not isinstance(coin, dict):
            continue
        created_ms = max(
            _timestamp_ms(coin.get("created_timestamp")),
            _timestamp_ms(coin.get("createdAt")),
        )
        if created_ms > day_ago_ms:
            count += 1
    return count


def merge_token_data(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merges two token payloads; non-empty ``overlay`` values win (BUG-95)."""
    merged = dict(base)
    for key, value in overlay.items():
        if value not in (None, "", [], {}) or key not in merged:
            merged[key] = value
    return merged


def creator_initial_buy_pct(
    coin_data: dict[str, Any], *, total_supply_ui: float = PUMP_TOTAL_SUPPLY_UI
) -> float | None:
    """Creator's share of supply from the create transaction's ``initialBuy``.

    PumpPortal reports ``initialBuy`` in whole tokens; raw base units are
    detected by size and scaled down (6 decimals).
    """
    raw = coin_data.get("initialBuy")
    if raw is None:
        return None
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if amount > total_supply_ui:
        amount /= 1_000_000.0
    return min(1.0, amount / total_supply_ui)


PUMP_MINT_SUFFIX = "pump"
SCREENING_EVENT = "screening"


def non_pump_launch_reason(
    mint: str, token_data: dict[str, Any] | None, *, require_suffix: bool = True
) -> str | None:
    """Why a stream token is not a Pump.fun bonding-curve launch, or ``None``.

    PumpPortal's new-token feed also carries other launchpads (``pool`` is then
    e.g. ``bonk``), and Stage 0 bought 263 such mints, USDC among them
    (BUG-108). Pump.fun's own launches get a vanity mint ending in ``pump``.
    This is the cheap first filter; the buy path still checks that the curve
    exists and is owned by the Pump.fun program.
    """
    pool = (token_data or {}).get("pool")
    if isinstance(pool, str) and pool.strip() and pool.strip().lower() != "pump":
        return f"launched on '{pool.strip()}', not Pump.fun"
    if require_suffix and not mint.endswith(PUMP_MINT_SUFFIX):
        return f"mint does not end in '{PUMP_MINT_SUFFIX}'"
    return None


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def screening_snapshot(
    verdict: TokenScreeningVerdict,
    *,
    name: str | None = None,
    market_cap_sol: float = 0.0,
    latency_ms: float | None = None,
    timestamp: float | None = None,
) -> dict[str, Any]:
    """Replay-capture record of what the screener saw for one token.

    Captures used to hold no social links, holders or creator history, so
    filters could not be tuned from them. The record has no price field and
    ``event = "screening"``, so the replay engine never treats it as a tick.
    """
    holders = verdict.holder_distribution
    metadata = verdict.metadata
    dev = verdict.dev_profile
    screening: dict[str, Any] = {
        "passed": bool(verdict.passed),
        "risk_score": _round(verdict.risk_score, 2),
        "reasons": list(verdict.reasons or []),
        "market_cap_sol": _round(market_cap_sol, 4),
        "latency_ms": _round(latency_ms, 1),
        "social_links": metadata.social_links_count() if metadata else None,
        "twitter": bool(metadata and metadata.twitter),
        "telegram": bool(metadata and metadata.telegram),
        "website": bool(metadata and metadata.website),
        "holders_available": bool(holders and holders.top_holders),
        "holder_count": len(holders.top_holders) if holders else 0,
        "top5_pct": _round(holders.compute_top5_non_curve_pct()) if holders else None,
        "gini": _round(holders.compute_gini_coefficient()) if holders else None,
        "creator_pct": _round(holders.creator_initial_pct) if holders else None,
        "creator": (dev.creator_address or None) if dev else None,
        "creator_launches_24h": dev.tokens_launched_24h if dev else None,
        "creator_total_launches": dev.total_tokens_launched if dev else None,
        "creator_rugs": dev.rug_history_count if dev else None,
        "flags": {
            key: value
            for key, value in (verdict.flags or {}).items()
            if isinstance(value, (bool, int, float, str)) or value is None
        },
    }
    return {
        "timestamp": time.time() if timestamp is None else timestamp,
        "mint": verdict.mint,
        "name": name or verdict.mint,
        "event": SCREENING_EVENT,
        "screening": screening,
    }


class TokenEnricher:
    """Handles off-chain token metadata enrichment, creator profiling, and anti-rug screening."""

    # Pause between holder lookups that came back empty (BUG-107).
    holder_retry_delay_seconds: float = 0.25

    def __init__(
        self,
        api_client: Optional[PumpFunApiClient] = None,
        execution_client: Optional[PumpFunExecutionClient] = None,
        config: Optional[TradingBotConfig] = None,
        strategy: Optional[TradingStrategy] = None,
        screening_cache: Optional[ScreeningCache] = None,
        lookup_timeout_seconds: float = DEFAULT_LOOKUP_TIMEOUT_SECONDS,
    ) -> None:
        self.api = api_client
        self.lookup_timeout_seconds = lookup_timeout_seconds
        self.execution = execution_client
        self.config = config or TradingBotConfig()
        self.strategy = strategy or TradingStrategy(self.config)
        self.screening_cache = screening_cache or ScreeningCache(
            default_ttl=float(self.config.screening_cache_ttl_seconds)
        )
        # ok / ok_after_retry / empty / error / timeout counts (BUG-107).
        self.holder_lookup_stats: dict[str, int] = {}

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

        # Stream payloads (e.g. PumpPortal newToken) carry no socials or holders, so
        # always look the token up and fetch on-chain holders, in parallel (BUG-95).
        fetched, chain_holders = await asyncio.gather(
            self._fetch_coin(mint), self._fetch_largest_holders(mint)
        )
        coin_data = merge_token_data(fetched, token_data or {})
        if not TokenMetadata.from_dict(coin_data).social_links_count():
            coin_data = merge_token_data(
                coin_data, await self._fetch_offchain_metadata(coin_data)
            )

        metadata = TokenMetadata.from_dict(coin_data) if coin_data else None

        dev_profile = None
        creator = (
            coin_data.get("creator")
            or coin_data.get("user")
            or coin_data.get("creatorAddress")
            or coin_data.get("dev_wallet")
            or coin_data.get("traderPublicKey")
        )
        if creator and isinstance(creator, str) and self.api:
            try:
                creator_coins = await asyncio.wait_for(
                    self.api.get_creator_coins(creator, limit=20),
                    timeout=self.lookup_timeout_seconds,
                )
                coins_list: list[Any] | None = None
                if isinstance(creator_coins, list):
                    coins_list = creator_coins
                elif isinstance(creator_coins, dict):
                    coins_list = (
                        creator_coins.get("coins") or creator_coins.get("items") or []
                    )
                if coins_list is not None:
                    # A real 24h count of 0 stays 0 (BUG-58).
                    dev_profile = DevWalletProfile(
                        creator_address=creator,
                        tokens_launched_24h=count_launches_last_24h(coins_list),
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
        if creator_holding_val is None:
            creator_holding_val = creator_initial_buy_pct(coin_data)
        creator_pct = (
            float(creator_holding_val) if creator_holding_val is not None else 0.0
        )

        if not isinstance(holders_data, list) and chain_holders:
            holder_distribution = HolderDistribution(
                creator_initial_pct=creator_pct,
                bonding_curve_address=bonding_curve_pda,
                top_holders=self._label_curve_account(mint, chain_holders),
            )
        elif isinstance(holders_data, list):
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

        cluster_analysis = None
        if active_config.enable_cluster_analysis:
            funding_links = (
                coin_data.get("funding_links") or coin_data.get("fundingLinks") or []
            )
            cluster_trades = (
                coin_data.get("trades") or coin_data.get("recent_trades") or []
            )
            if funding_links or coin_data.get("cluster_analysis"):
                if isinstance(coin_data.get("cluster_analysis"), dict):
                    # Direct verdict passed
                    pass
                top_h = holder_distribution.top_holders if holder_distribution else []
                total_supp = (
                    holder_distribution.total_supply
                    if holder_distribution
                    else 1_000_000_000_000_000
                )
                cluster_analysis = self.strategy.evaluate_cluster_graph(
                    mint,
                    top_holders=top_h,
                    creator_wallet=str(creator) if creator else None,
                    creator_balance=(
                        int(creator_pct * total_supp) if creator_pct > 0 else 0
                    ),
                    total_supply=total_supp,
                    funding_links=(
                        funding_links if isinstance(funding_links, list) else None
                    ),
                    trades=cluster_trades if isinstance(cluster_trades, list) else None,
                )

        verdict = self.strategy.screen_token(
            mint,
            metadata=metadata,
            dev_profile=dev_profile,
            holder_distribution=holder_distribution,
            bonding_curve_pda=bonding_curve_pda,
            cluster_analysis=cluster_analysis,
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

    async def _fetch_coin(self, mint: str) -> dict[str, Any]:
        """Pump.fun API record for the mint, or ``{}`` if not (yet) indexed."""
        if not self.api:
            return {}
        try:
            fetched = await asyncio.wait_for(
                self.api.get_coin(mint), timeout=self.lookup_timeout_seconds
            )
        except Exception as exc:
            logger.debug("Metadata query for %s failed during screening: %s", mint, exc)
            return {}
        return fetched if isinstance(fetched, dict) else {}

    async def _fetch_offchain_metadata(
        self, coin_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Metadata JSON behind the token ``uri`` (socials live there), or ``{}``."""
        uri = (
            coin_data.get("uri")
            or coin_data.get("metadata_uri")
            or coin_data.get("metadataUri")
        )
        if not self.api or not isinstance(uri, str) or not uri.strip():
            return {}
        try:
            fetched = await asyncio.wait_for(
                self.api.fetch_token_metadata(uri),
                timeout=self.lookup_timeout_seconds,
            )
        except Exception as exc:
            logger.debug("Token metadata fetch from %s failed: %s", uri, exc)
            return {}
        if not isinstance(fetched, dict):
            return {}
        # Only take social fields; the URI JSON's own "uri"/"image" keys are not ours.
        return {
            key: fetched[key]
            for key in (
                "description",
                "twitter",
                "telegram",
                "website",
                "discord",
                "extensions",
                "links",
                "socials",
            )
            if key in fetched
        }

    async def _fetch_largest_holders(self, mint: str) -> list[tuple[str, int]]:
        """On-chain largest token accounts for the mint, or ``[]`` on failure.

        ``getTokenLargestAccounts`` on a load-balanced RPC flaps for a brand-new
        mint: the same mint returns its holders, then ``[]``, then its holders
        again within seconds. An empty answer therefore means "not indexed on
        this node yet", not "no holders", and is retried inside the lookup
        budget (BUG-107). Outcomes are counted in ``holder_lookup_stats``.
        """
        if not self.execution:
            return []
        try:
            holders, outcome = await asyncio.wait_for(
                self._largest_holders_with_retry(mint),
                timeout=self.lookup_timeout_seconds,
            )
        except asyncio.TimeoutError:
            holders, outcome = [], "timeout"
        self.holder_lookup_stats[outcome] = self.holder_lookup_stats.get(outcome, 0) + 1
        if not holders:
            logger.debug("Largest-holder query for %s gave no data (%s)", mint, outcome)
        return holders

    async def _largest_holders_with_retry(
        self, mint: str
    ) -> tuple[list[tuple[str, int]], str]:
        execution = self.execution
        if execution is None:  # pragma: no cover - checked by the caller
            return [], "error"
        # One slow node must not use up the whole budget.
        per_call_timeout = max(0.5, self.lookup_timeout_seconds / 2)
        outcome = "empty"
        for attempt in range(HOLDER_LOOKUP_ATTEMPTS):
            if attempt:
                await asyncio.sleep(self.holder_retry_delay_seconds)
            try:
                holders = await execution.get_token_largest_accounts(
                    mint, timeout_seconds=per_call_timeout
                )
            except Exception as exc:
                logger.debug("Largest-holder query for %s failed: %s", mint, exc)
                outcome = "error"
                continue
            if isinstance(holders, list) and holders:
                return holders, "ok" if attempt == 0 else "ok_after_retry"
            outcome = "empty"
        return [], outcome

    def _label_curve_account(
        self, mint: str, holders: list[tuple[str, int]]
    ) -> list[tuple[str, int]]:
        """Relabels the bonding curve's token account with the curve PDA.

        ``getTokenLargestAccounts`` returns token accounts, so the curve's tokens sit
        in its associated account. Using the PDA lets the top-5 and Gini checks
        exclude it.
        """
        if not self.execution:  # pragma: no cover - holders imply an execution client
            return list(holders)
        try:
            curve_pda = ""
            curve_accounts: set[str] = set()
            for program in (_SPL_TOKEN_PROGRAM, _TOKEN_2022_PROGRAM):
                pda, associated = self.execution.get_bonding_curve_pda(
                    mint, token_program=program
                )
                curve_pda = str(pda)
                curve_accounts.add(str(associated))
        except Exception:
            return list(holders)
        return [
            (curve_pda if addr in curve_accounts else addr, amount)
            for addr, amount in holders
        ]
