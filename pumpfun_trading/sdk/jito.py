"""Jito Block Engine JSON-RPC client, tip floor tracker, and bundle builder.

This module provides MEV protection and private transaction bundling via Jito,
preventing toxic sandwich attacks and frontrunning on Solana decentralized exchanges.
"""

from __future__ import annotations

import asyncio
import base64
import json
import random
import time
from dataclasses import dataclass, field
from time import monotonic as _monotonic
from typing import Any, Optional, Sequence, Union

import aiohttp
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# Official Jito Validator Tip Accounts
JITO_TIP_ACCOUNTS: list[str] = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTxvQssQamRxUBvu13Wqh4KZxGar46YoxrfP",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]

# Official Jito Block Engine Regional Endpoints
JITO_BLOCK_ENGINE_ENDPOINTS: dict[str, str] = {
    "mainnet": "https://mainnet.block-engine.jito.wtf",
    "amsterdam": "https://amsterdam.mainnet.block-engine.jito.wtf",
    "frankfurt": "https://frankfurt.mainnet.block-engine.jito.wtf",
    "ny": "https://ny.mainnet.block-engine.jito.wtf",
    "tokyo": "https://tokyo.mainnet.block-engine.jito.wtf",
}

DEFAULT_TIP_FLOOR_URL = "https://bundles.jito.wtf/api/v1/bundles/tip_floor"


@dataclass
class JitoTipFloor:
    """Historical and real-time tip floor percentiles queried from Jito."""

    time: str = ""
    p25_landed_tip_sol: float = 0.00001
    p50_landed_tip_sol: float = 0.00005
    p75_landed_tip_sol: float = 0.0001
    p95_landed_tip_sol: float = 0.001
    p99_landed_tip_sol: float = 0.005
    ema_p50_landed_tip_sol: float = 0.00005
    raw_data: dict[str, Any] = field(default_factory=dict)
    fetched_at: float = field(default_factory=_monotonic)

    def get_percentile_sol(self, percentile: str = "50th") -> float:
        """Return tip in SOL for the given percentile (25th, 50th, 75th, 95th, 99th, ema)."""
        key = (
            percentile.lower()
            .replace("_percentile", "")
            .replace("th", "")
            .replace("p", "")
        )
        if key in {"25", "p25"}:
            return self.p25_landed_tip_sol
        if key in {"75", "p75"}:
            return self.p75_landed_tip_sol
        if key in {"95", "p95"}:
            return self.p95_landed_tip_sol
        if key in {"99", "p99"}:
            return self.p99_landed_tip_sol
        if key in {"ema", "ema50"}:
            return self.ema_p50_landed_tip_sol
        return self.p50_landed_tip_sol

    def get_percentile_lamports(self, percentile: str = "50th") -> int:
        """Return tip in integer Lamports for the given percentile."""
        sol_amount = self.get_percentile_sol(percentile)
        return int(max(0.0, sol_amount) * 1_000_000_000)


@dataclass
class JitoTipConfig:
    """Configuration for dynamic Jito tip calculation and rate bounding."""

    min_tip_lamports: int = 10_000  # 0.00001 SOL minimum tip
    max_tip_lamports: int = 100_000_000  # 0.1 SOL maximum cap
    default_tip_lamports: int = 100_000  # 0.0001 SOL default fallback
    tip_percentile: str = "50th"
    tip_pct_of_trade: float = 0.005  # 0.5% of trade value default
    conviction_scaling: bool = True
    tip_multiplier: float = 1.0


@dataclass
class JitoBundleStatus:
    """Status details for a submitted Jito bundle."""

    bundle_id: str
    status: str  # "Pending", "Landed", "Failed", "Invalid", "Unknown"
    slot: Optional[int] = None
    confirmation_status: Optional[str] = None  # "processed", "confirmed", "finalized"
    err: Optional[Any] = None
    transactions: list[str] = field(default_factory=list)

    @property
    def is_landed(self) -> bool:
        """Check if bundle landed on-chain."""
        return self.status.lower() == "landed" or self.confirmation_status in {
            "confirmed",
            "finalized",
        }

    @property
    def is_failed(self) -> bool:
        """Check if bundle submission failed or encountered execution errors."""
        return self.status.lower() in {"failed", "invalid"} or self.err is not None


@dataclass
class JitoBundle:
    """Container for atomic transactions grouped for private Jito submission."""

    transactions: list[VersionedTransaction]
    tip_lamports: int
    tip_account: str
    bundle_id: Optional[str] = None


class JitoClient:
    """Asynchronous client for Jito Block Engine JSON-RPC and Tip Floor APIs."""

    def __init__(
        self,
        wallet: Optional[Union[Keypair, Pubkey, str]] = None,
        *,
        block_engine_url: str = JITO_BLOCK_ENGINE_ENDPOINTS["mainnet"],
        tip_floor_url: str = DEFAULT_TIP_FLOOR_URL,
        tip_accounts: Optional[Sequence[str]] = None,
        config: Optional[JitoTipConfig] = None,
        session: Optional[aiohttp.ClientSession] = None,
        request_timeout: float = 10.0,
    ) -> None:
        self.wallet = self._parse_wallet_pubkey(wallet) if wallet is not None else None
        self.block_engine_url = block_engine_url.rstrip("/")
        self.tip_floor_url = tip_floor_url
        self.tip_accounts: list[str] = (
            list(tip_accounts) if tip_accounts else list(JITO_TIP_ACCOUNTS)
        )
        self.config = config or JitoTipConfig()
        self.request_timeout = request_timeout
        self._session = session
        self._owns_session = session is None
        self._tip_account_index = 0
        self._cached_tip_floor: Optional[JitoTipFloor] = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _parse_wallet_pubkey(wallet: Union[Keypair, Pubkey, str]) -> Pubkey:
        if isinstance(wallet, Keypair):
            return wallet.pubkey()
        if isinstance(wallet, Pubkey):
            return wallet
        return Pubkey.from_string(str(wallet))

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.request_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        """Close the internal HTTP session if owned."""
        if (
            self._owns_session
            and self._session is not None
            and not self._session.closed
        ):
            await self._session.close()

    async def __aenter__(self) -> JitoClient:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def get_tip_account(self, random_pick: bool = False) -> str:
        """Return a validator tip account, rotating sequentially or randomly."""
        if not self.tip_accounts:
            self.tip_accounts = list(JITO_TIP_ACCOUNTS)
        if random_pick:
            return random.choice(self.tip_accounts)
        account = self.tip_accounts[self._tip_account_index % len(self.tip_accounts)]
        self._tip_account_index = (self._tip_account_index + 1) % len(self.tip_accounts)
        return account

    async def refresh_tip_accounts(self) -> list[str]:
        """Query Block Engine JSON-RPC for the current list of active tip accounts."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTipAccounts",
            "params": [],
        }
        try:
            result = await self._send_json_rpc(payload)
            if (
                isinstance(result, list)
                and all(isinstance(x, str) for x in result)
                and result
            ):
                self.tip_accounts = result
                return result
        except Exception:
            pass
        return self.tip_accounts

    async def fetch_tip_floor(self, max_age_seconds: float = 10.0) -> JitoTipFloor:
        """Query Jito tip stream API for landed tip percentiles with caching."""
        if (
            self._cached_tip_floor is not None
            and (time.monotonic() - self._cached_tip_floor.fetched_at) < max_age_seconds
        ):
            return self._cached_tip_floor

        session = await self._get_session()
        try:
            async with session.get(self.tip_floor_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    item = data[0] if isinstance(data, list) and len(data) > 0 else data
                    if isinstance(item, dict):
                        floor = JitoTipFloor(
                            time=str(item.get("time", "")),
                            p25_landed_tip_sol=float(
                                item.get("landed_tips_25th_percentile", 0.00001)
                            ),
                            p50_landed_tip_sol=float(
                                item.get("landed_tips_50th_percentile", 0.00005)
                            ),
                            p75_landed_tip_sol=float(
                                item.get("landed_tips_75th_percentile", 0.0001)
                            ),
                            p95_landed_tip_sol=float(
                                item.get("landed_tips_95th_percentile", 0.001)
                            ),
                            p99_landed_tip_sol=float(
                                item.get("landed_tips_99th_percentile", 0.005)
                            ),
                            ema_p50_landed_tip_sol=float(
                                item.get("ema_landed_tips_50th_percentile", 0.00005)
                            ),
                            raw_data=item,
                            fetched_at=time.monotonic(),
                        )
                        self._cached_tip_floor = floor
                        return floor
        except Exception:
            pass

        if self._cached_tip_floor is not None:
            return self._cached_tip_floor

        # Fallback default floor
        default_floor = JitoTipFloor(
            p25_landed_tip_sol=0.00001,
            p50_landed_tip_sol=0.00005,
            p75_landed_tip_sol=0.0001,
            p95_landed_tip_sol=0.001,
            p99_landed_tip_sol=0.005,
            ema_p50_landed_tip_sol=0.00005,
            fetched_at=time.monotonic(),
        )
        self._cached_tip_floor = default_floor
        return default_floor

    def calculate_tip_lamports(
        self,
        trade_amount_sol: float = 0.0,
        conviction_score: float = 1.0,
        *,
        percentile: Optional[str] = None,
        tip_floor: Optional[JitoTipFloor] = None,
    ) -> int:
        """Calculate dynamic tip in Lamports based on trade size, percentile floor, and conviction."""
        target_percentile = percentile or self.config.tip_percentile
        floor = tip_floor or self._cached_tip_floor

        if floor is not None:
            floor_lamports = floor.get_percentile_lamports(target_percentile)
        else:
            floor_lamports = self.config.default_tip_lamports

        # Value-based scaling (percentage of trade size in SOL converted to lamports)
        trade_lamports = int(max(0.0, trade_amount_sol) * 1_000_000_000)
        value_tip_lamports = int(trade_lamports * self.config.tip_pct_of_trade)

        # Base candidate is highest between percentile floor and trade fraction
        base_tip = max(floor_lamports, value_tip_lamports)

        # Scale by conviction score if enabled (clamped between 0.5x and 3.0x)
        multiplier = self.config.tip_multiplier
        if self.config.conviction_scaling:
            conviction_clamped = max(0.5, min(3.0, float(conviction_score)))
            multiplier *= conviction_clamped

        calculated = int(base_tip * multiplier)

        # Enforce bounds
        bounded = max(
            self.config.min_tip_lamports, min(self.config.max_tip_lamports, calculated)
        )
        return bounded

    def build_tip_instruction(
        self,
        payer: Union[Pubkey, str],
        tip_lamports: int,
        tip_account: Optional[Union[Pubkey, str]] = None,
    ) -> Instruction:
        """Construct SystemProgram transfer instruction sending tip lamports to validator account."""
        if tip_lamports <= 0:
            raise ValueError(
                f"Tip lamports must be strictly positive, got {tip_lamports}"
            )

        payer_pubkey = (
            payer if isinstance(payer, Pubkey) else Pubkey.from_string(str(payer))
        )
        recipient = tip_account or self.get_tip_account()
        recipient_pubkey = (
            recipient
            if isinstance(recipient, Pubkey)
            else Pubkey.from_string(str(recipient))
        )

        # System Program Transfer instruction: index 2 (4 bytes little endian) + lamports u64
        data = bytes([2, 0, 0, 0]) + tip_lamports.to_bytes(
            8, byteorder="little", signed=False
        )
        accounts = [
            AccountMeta(pubkey=payer_pubkey, is_signer=True, is_writable=True),
            AccountMeta(pubkey=recipient_pubkey, is_signer=False, is_writable=True),
        ]
        return Instruction(
            program_id=Pubkey.from_string(SYSTEM_PROGRAM_ID),
            accounts=accounts,
            data=data,
        )

    async def _send_json_rpc(
        self,
        payload: dict[str, Any],
        endpoint_url: Optional[str] = None,
    ) -> Any:
        url = endpoint_url or f"{self.block_engine_url}/api/v1/bundles"
        session = await self._get_session()
        async with session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
        ) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(
                    f"Jito Block Engine JSON-RPC failed (HTTP {resp.status}): {text[:500]}"
                )
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as err:
                raise RuntimeError(
                    f"Invalid JSON returned from Jito endpoint: {text[:500]}"
                ) from err

            if "error" in parsed and parsed["error"] is not None:
                raise RuntimeError(f"Jito JSON-RPC returned error: {parsed['error']}")
            return parsed.get("result")

    async def send_bundle(
        self,
        transactions: Sequence[Union[VersionedTransaction, str]],
        *,
        endpoint_url: Optional[str] = None,
    ) -> str:
        """Serialize and submit an atomic bundle of transactions to Jito Block Engine."""
        if not transactions:
            raise ValueError("Cannot submit an empty Jito bundle")
        if len(transactions) > 5:
            raise ValueError(
                f"Jito bundles support at most 5 transactions, got {len(transactions)}"
            )

        encoded_txs: list[str] = []
        for tx in transactions:
            if isinstance(tx, VersionedTransaction):
                encoded_txs.append(base64.b64encode(bytes(tx)).decode("utf-8"))
            elif isinstance(tx, str):
                encoded_txs.append(tx)
            else:
                raise TypeError(f"Unsupported transaction type: {type(tx)}")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [encoded_txs],
        }

        result = await self._send_json_rpc(payload, endpoint_url=endpoint_url)
        if not result:
            raise RuntimeError(f"Missing bundle ID in Jito response: {result}")
        return str(result)

    async def get_bundle_statuses(
        self,
        bundle_ids: Sequence[str],
        *,
        endpoint_url: Optional[str] = None,
    ) -> list[JitoBundleStatus]:
        """Fetch confirmation statuses for a list of bundle IDs."""
        if not bundle_ids:
            return []

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBundleStatuses",
            "params": [list(bundle_ids)],
        }
        result = await self._send_json_rpc(payload, endpoint_url=endpoint_url)
        statuses: list[JitoBundleStatus] = []
        if isinstance(result, dict):
            value = result.get("value", [])
            for item in value:
                if isinstance(item, dict):
                    b_id = str(item.get("bundle_id", ""))
                    conf_status = item.get("confirmation_status")
                    err = item.get("err")
                    slot = item.get("slot")
                    txs = item.get("transactions", [])
                    status_str = (
                        "Landed"
                        if conf_status in {"confirmed", "finalized"}
                        else "Pending"
                    )
                    if err is not None:
                        status_str = "Failed"
                    statuses.append(
                        JitoBundleStatus(
                            bundle_id=b_id,
                            status=status_str,
                            slot=slot,
                            confirmation_status=conf_status,
                            err=err,
                            transactions=txs if isinstance(txs, list) else [],
                        )
                    )
        return statuses

    async def get_inflight_bundle_statuses(
        self,
        bundle_ids: Sequence[str],
        *,
        endpoint_url: Optional[str] = None,
    ) -> list[JitoBundleStatus]:
        """Fetch in-flight statuses for active bundles."""
        if not bundle_ids:
            return []

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getInflightBundleStatuses",
            "params": [list(bundle_ids)],
        }
        result = await self._send_json_rpc(payload, endpoint_url=endpoint_url)
        statuses: list[JitoBundleStatus] = []
        if isinstance(result, dict):
            value = result.get("value", [])
            for item in value:
                if isinstance(item, dict):
                    b_id = str(item.get("bundle_id", ""))
                    status_str = str(item.get("status", "Pending"))
                    slot = item.get("landed_slot")
                    statuses.append(
                        JitoBundleStatus(
                            bundle_id=b_id,
                            status=status_str,
                            slot=slot,
                        )
                    )
        return statuses

    async def wait_for_bundle_confirmation(
        self,
        bundle_id: str,
        *,
        timeout_seconds: float = 12.0,
        poll_interval: float = 0.5,
    ) -> JitoBundleStatus:
        """Poll bundle confirmation status until landed, finalized, or failed."""
        start_time = time.monotonic()
        while (time.monotonic() - start_time) < timeout_seconds:
            statuses = await self.get_bundle_statuses([bundle_id])
            for st in statuses:
                if st.bundle_id == bundle_id:
                    if st.is_landed or st.is_failed:
                        return st
            await asyncio.sleep(poll_interval)

        raise TimeoutError(
            f"Timed out waiting for Jito bundle confirmation: {bundle_id}"
        )


__all__ = [
    "DEFAULT_TIP_FLOOR_URL",
    "JITO_BLOCK_ENGINE_ENDPOINTS",
    "JITO_TIP_ACCOUNTS",
    "JitoBundle",
    "JitoBundleStatus",
    "JitoClient",
    "JitoTipConfig",
    "JitoTipFloor",
]
