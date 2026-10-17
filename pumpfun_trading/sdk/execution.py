import asyncio
import base64
import json
from typing import Any, Optional

import aiohttp
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.models import CloseAccountParams, SyncNativeParams
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
    sync_native,
)

from pumpfun_trading.infra.rpc_pool import (
    RpcConnectionPool,
)
from .costs import (
    TransactionCosts,
    model_transaction_costs,
    parse_transaction_costs,
)
from .curve import (
    calculate_buy_execution_slippage,
    calculate_buy_price_impact,
    calculate_buy_tokens_out,
    calculate_market_cap_sol,
    calculate_sell_execution_slippage,
    calculate_sell_price_impact,
    calculate_sell_sol_out,
    calculate_spot_price,
    curve_reserve_anomaly,
)
from .jito import (
    JITO_BLOCK_ENGINE_ENDPOINTS,
    JITO_TIP_ACCOUNTS,
    JitoClient,
    JitoTipConfig,
)
from .raydium import (
    RaydiumPoolKeys,
    build_raydium_swap_instruction,
    calculate_raydium_swap_out,
)

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
GLOBAL_STATE = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
FEE_RECIPIENT = "FWsW1xNtWscwNmKv6wVsU1iTzRN6wmmk3MjxRP5tT7hz"
# Global.reserved_fee_recipient: mandatory fee recipient for mayhem-mode curves
MAYHEM_FEE_RECIPIENT = "GesfTA3X2arioaHp8bbKdjG9vJtskViWACZoYvxp4twS"
BUYBACK_FEE_RECIPIENT = "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD"
PUMP_FEE_PROGRAM_ID = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
WSOL_MINT_STR = "So11111111111111111111111111111111111111112"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"
RENT_PROGRAM_ID = "SysvarRent111111111111111111111111111111111"
EVENT_AUTHORITY = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"
TOKEN_PROGRAM_ID_STR = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID_STR = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"

BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])
BUY_V2_DISCRIMINATOR = bytes([184, 23, 238, 97, 103, 197, 211, 61])
SELL_V2_DISCRIMINATOR = bytes([93, 246, 130, 60, 231, 233, 64, 178])

FEE_CONFIG_KEY = bytes(
    [
        1,
        86,
        224,
        246,
        147,
        102,
        90,
        207,
        68,
        219,
        21,
        104,
        191,
        23,
        91,
        170,
        81,
        137,
        203,
        151,
        245,
        210,
        255,
        59,
        101,
        93,
        43,
        182,
        253,
        109,
        24,
        176,
    ]
)


# Pump.fun bonding-curve fees (protocol 0.95% + creator 0.30%) applied to quotes.
PUMP_DEFAULT_FEE_BPS = 125


class TokenBalanceUnavailableError(RuntimeError):
    """The token balance could not be read; distinct from a real zero (BUG-35)."""


class TokenProgramUnavailableError(RuntimeError):
    """The mint's token program (SPL Token vs Token-2022) could not be resolved."""


class CurveStateUnavailableError(RuntimeError):
    """The bonding curve (and its creator) could not be fetched for a trade."""


class NonStandardCurveError(CurveStateUnavailableError):
    """The curve's reserves don't match the standard Pump.fun layout (BUG-104)."""


class NotPumpFunCurveError(CurveStateUnavailableError):
    """The mint has no bonding curve owned by the Pump.fun program (BUG-108)."""


class PumpFunExecutionClient:
    """Build and broadcast real Pump.fun transactions using the program instruction pattern."""

    pump_fee_bps: int = PUMP_DEFAULT_FEE_BPS

    @staticmethod
    def normalize_slippage_bps(value: int | None, default: int = 500) -> int:
        """Normalize a slippage value into basis points, clamping invalid values."""
        if value is None:
            return max(0, min(default, 10_000))
        if isinstance(value, bool):
            raise ValueError("Slippage must be an integer number of basis points")
        numeric = int(value)
        if numeric < 0:
            raise ValueError("Slippage cannot be negative")
        if numeric > 10_000:
            raise ValueError("Slippage cannot exceed 100% (10,000 bps)")
        return numeric

    @staticmethod
    def evaluate_fill_completion(
        expected_amount: int,
        actual_amount: int,
        *,
        minimum_partial_ratio: float = 0.1,
    ) -> dict[str, int | str | float | bool]:
        """Classify a fill event as full, partial, or failed.

        This is intentionally lightweight and reusable by the bot when a transaction result
        indicates only a subset of the requested tokens were filled.
        """
        expected = max(0, int(expected_amount))
        actual = max(0, int(actual_amount))
        if actual <= 0:
            return {
                "status": "failed",
                "expected_amount": expected,
                "actual_amount": actual,
                "remaining_amount": expected,
                "partial": False,
                "fill_ratio": 0.0,
            }
        if actual >= expected:
            return {
                "status": "full",
                "expected_amount": expected,
                "actual_amount": actual,
                "remaining_amount": max(0, expected - actual),
                "partial": False,
                "fill_ratio": 1.0,
            }
        ratio = actual / expected if expected else 0.0
        return {
            "status": "partial",
            "expected_amount": expected,
            "actual_amount": actual,
            "remaining_amount": expected - actual,
            "partial": True,
            "fill_ratio": ratio,
        }

    @staticmethod
    def should_reassess_partial_fill(
        expected_amount: int,
        actual_amount: int,
        *,
        minimum_partial_ratio: float = 0.1,
    ) -> bool:
        """Return True if a partial fill is material enough that it should be re-evaluated."""
        if expected_amount <= 0 or actual_amount <= 0:
            return False
        ratio = actual_amount / expected_amount
        return 0.0 < ratio < 1.0 and ratio >= minimum_partial_ratio

    @staticmethod
    def classify_execution_error(exc: Exception | str) -> str:
        """Classify common transient execution and RPC failures."""
        text = str(exc).lower()
        if "timeout" in text or "timed out" in text:
            return "rpc_timeout"
        if "429" in text or "rate limit" in text:
            return "rate_limited"
        if "connection" in text or "network" in text or "dns" in text:
            return "network_error"
        if (
            "http 5" in text
            or "500" in text
            or "502" in text
            or "503" in text
            or "504" in text
        ):
            return "server_error"
        if "signature" in text or "transaction" in text and "failed" in text:
            return "transaction_failed"
        return "unknown"

    @staticmethod
    def sol_to_lamports(sol_amount: float | int) -> int:
        """Convert SOL value to integer Lamports."""
        if sol_amount < 0:
            raise ValueError("SOL amount cannot be negative")
        return int(round(float(sol_amount) * 1_000_000_000))

    @staticmethod
    def lamports_to_sol(lamports: int) -> float:
        """Convert Lamports value to floating-point SOL."""
        if lamports < 0:
            raise ValueError("Lamports cannot be negative")
        return float(lamports) / 1_000_000_000.0

    @staticmethod
    def decode_bonding_curve_data(data: bytes) -> dict[str, Any]:
        """Decode raw Solana account data of a Pump.fun bonding curve.

        Layout:
          0..8: Discriminator (u64 / 8 bytes)
          8..16: virtual_token_reserves (u64)
          16..24: virtual_sol_reserves (u64)
          24..32: real_token_reserves (u64)
          32..40: real_sol_reserves (u64)
          40..48: token_total_supply (u64)
          48..49: complete (bool)
          49..81: creator (Pubkey)
          81..82: is_mayhem_mode (bool)
        """
        if len(data) < 49:
            raise ValueError(
                f"Bonding curve account data too short: {len(data)} bytes (expected >= 49)"
            )
        virtual_token_reserves = int.from_bytes(
            data[8:16], byteorder="little", signed=False
        )
        virtual_sol_reserves = int.from_bytes(
            data[16:24], byteorder="little", signed=False
        )
        real_token_reserves = int.from_bytes(
            data[24:32], byteorder="little", signed=False
        )
        real_sol_reserves = int.from_bytes(
            data[32:40], byteorder="little", signed=False
        )
        token_total_supply = int.from_bytes(
            data[40:48], byteorder="little", signed=False
        )
        complete = bool(data[48])
        creator = None
        if len(data) >= 81:
            try:
                creator_pk = Pubkey.from_bytes(data[49:81])
                creator = str(creator_pk)
            except Exception:
                creator = None
        is_mayhem_mode = bool(data[81]) if len(data) >= 82 else False

        price_sol = (
            (virtual_sol_reserves / 1_000_000_000.0)
            / (virtual_token_reserves / 1_000_000.0)
            if virtual_token_reserves > 0
            else 0.0
        )
        market_cap_sol = (
            (virtual_sol_reserves / 1_000_000_000.0)
            * (token_total_supply / float(virtual_token_reserves))
            if virtual_token_reserves > 0
            else 0.0
        )

        return {
            "virtual_token_reserves": virtual_token_reserves,
            "virtual_sol_reserves": virtual_sol_reserves,
            "real_token_reserves": real_token_reserves,
            "real_sol_reserves": real_sol_reserves,
            "token_total_supply": token_total_supply,
            "complete": complete,
            "price_sol": price_sol,
            "market_cap_sol": market_cap_sol,
            "creator": creator,
            "is_mayhem_mode": is_mayhem_mode,
        }

    calculate_buy_tokens_out = staticmethod(calculate_buy_tokens_out)
    calculate_sell_sol_out = staticmethod(calculate_sell_sol_out)
    calculate_buy_price_impact = staticmethod(calculate_buy_price_impact)
    calculate_sell_price_impact = staticmethod(calculate_sell_price_impact)
    calculate_buy_execution_slippage = staticmethod(calculate_buy_execution_slippage)
    calculate_sell_execution_slippage = staticmethod(calculate_sell_execution_slippage)
    calculate_spot_price = staticmethod(calculate_spot_price)
    calculate_market_cap_sol = staticmethod(calculate_market_cap_sol)

    @staticmethod
    def calculate_sell_sol_output(
        token_amount: int,
        virtual_token_reserves: int,
        virtual_sol_reserves: int,
        *,
        slippage_bps: int = 0,
    ) -> int:
        """Calculate minimum output Lamports for selling a token amount on the bonding curve."""
        return calculate_sell_sol_out(
            token_amount=token_amount,
            virtual_token_reserves=virtual_token_reserves,
            virtual_sol_reserves=virtual_sol_reserves,
            slippage_bps=slippage_bps,
        )

    @staticmethod
    def _decode_keypair(private_key_b58: str) -> Keypair:
        from pumpfun_trading.config.env import decode_keypair

        return decode_keypair(private_key_b58)

    def __init__(
        self,
        private_key_b58: str,
        rpc_url: Optional[str] = None,
        *,
        rpc_pool: Optional[RpcConnectionPool] = None,
        rpc_urls: Optional[list[str] | tuple[str, ...]] = None,
        priority_fee_lamports: int = 5000,
        compute_unit_limit: int = 200_000,
        compute_unit_price_micro_lamports: Optional[int] = None,
        jito_tip_lamports: int = 0,
        jito_block_engine_url: Optional[str] = None,
        use_jito: bool = False,
        jito_fallback_to_rpc: bool = True,
        jito_confirmation_timeout: float = 12.0,
        jito_client: Optional[JitoClient] = None,
        jito_tip_config: Optional[JitoTipConfig] = None,
        default_slippage_bps: int = 500,
    ):
        self.private_key_b58 = private_key_b58

        # Initialize multi-provider RPC connection pool
        if rpc_pool is not None:
            self.rpc_pool = rpc_pool
            self.rpc_url = rpc_url or (
                rpc_pool.endpoints[0].url
                if rpc_pool.endpoints
                else "https://api.mainnet-beta.solana.com"
            )
        else:
            endpoints_list: list[str] = []
            if rpc_urls:
                endpoints_list.extend(rpc_urls)
            if rpc_url and rpc_url not in endpoints_list:
                endpoints_list.insert(0, rpc_url)
            if not endpoints_list:
                endpoints_list = ["https://api.mainnet-beta.solana.com"]
            self.rpc_pool = RpcConnectionPool(endpoints=tuple(endpoints_list))
            self.rpc_url = endpoints_list[0]

        self.priority_fee_lamports = priority_fee_lamports
        self.compute_unit_limit = compute_unit_limit
        self.compute_unit_price_micro_lamports = compute_unit_price_micro_lamports
        self.jito_tip_lamports = jito_tip_lamports
        self.jito_block_engine_url = jito_block_engine_url
        self.use_jito = bool(use_jito or jito_tip_lamports > 0 or jito_block_engine_url)
        self.jito_fallback_to_rpc = jito_fallback_to_rpc
        self.jito_confirmation_timeout = jito_confirmation_timeout
        self.default_slippage_bps = self.normalize_slippage_bps(default_slippage_bps)
        self.keypair = self._decode_keypair(private_key_b58)
        self.wallet = self.keypair.pubkey()
        self._execution_lock = asyncio.Lock()
        self.execution_health_score = 100.0
        self.failed_execution_attempts = 0
        self.jito_tip_config = jito_tip_config or JitoTipConfig()
        self.jito_client: Optional[JitoClient] = jito_client
        if self.jito_client is None and self.use_jito:
            self.jito_client = JitoClient(
                wallet=self.wallet,
                block_engine_url=self.jito_block_engine_url
                or JITO_BLOCK_ENGINE_ENDPOINTS["mainnet"],
                config=self.jito_tip_config,
            )

    async def _request_rpc_json(
        self,
        payload: dict,
        *,
        max_retries: int = 3,
        timeout_seconds: float = 20.0,
    ) -> dict:
        try:
            parsed = await self.rpc_pool.request(
                payload, max_retries=max_retries, timeout_seconds=timeout_seconds
            )
            self.execution_health_score = min(100.0, self.execution_health_score + 1.0)
            return parsed
        except Exception as exc:
            self.failed_execution_attempts += 1
            self.execution_health_score = max(0.0, self.execution_health_score - 10.0)
            raise RuntimeError(f"RPC request failed after retries: {exc}") from exc

    @staticmethod
    def is_valid_pubkey(value: str) -> bool:
        try:
            Pubkey.from_string(value)
            return True
        except Exception:
            return False

    @staticmethod
    def is_valid_mint(value: str) -> bool:
        return (
            isinstance(value, str)
            and len(value) >= 32
            and PumpFunExecutionClient.is_valid_pubkey(value)
        )

    def _to_pubkey(self, value: str | Pubkey) -> Pubkey:
        if isinstance(value, Pubkey):
            return value
        return Pubkey.from_string(value)

    @staticmethod
    def _u64(value: int) -> bytes:
        if value < 0:
            raise ValueError("Unsigned integer cannot be negative")
        return value.to_bytes(8, byteorder="little", signed=False)

    def get_wallet_pubkey(self) -> str:
        return str(self.wallet)

    async def get_latest_blockhash(self) -> str:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getLatestBlockhash",
            "params": [{"commitment": "confirmed"}],
        }
        parsed = await self._request_rpc_json(payload)
        value = parsed.get("result", {}).get("value", {})
        blockhash = value.get("blockhash")
        if not isinstance(blockhash, str):
            raise RuntimeError(f"Invalid blockhash response: {parsed}")
        return blockhash

    async def get_balance_sol(self) -> float:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [str(self.wallet)],
        }
        parsed = await self._request_rpc_json(payload)
        result = parsed.get("result") or {}
        lamports = int(result.get("value", 0)) if isinstance(result, dict) else 0
        return lamports / 1_000_000_000.0

    async def get_wallet_balance_sol(self) -> float:
        """Alias for get_balance_sol for backward compatibility."""
        return await self.get_balance_sol()

    async def get_token_program_for_mint(self, mint: str) -> Pubkey:
        """Query mint account to determine if it uses Token-2022 or legacy SPL Token program.

        Results are cached per mint. Raises if the owner cannot be read, because
        guessing SPL Token for a Token-2022 mint builds a failing trade (BUG-69).
        """
        cache: dict[str, Pubkey] = self.__dict__.setdefault("_token_program_cache", {})
        cached = cache.get(mint)
        if cached is not None:
            return cached
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [mint, {"encoding": "jsonParsed"}],
        }
        last_error: Exception | None = None
        for _ in range(2):
            try:
                parsed = await self.rpc_pool.request(
                    payload, max_retries=1, timeout_seconds=3.0
                )
                value = (parsed.get("result") or {}).get("value")
                if value and "owner" in value:
                    program = Pubkey.from_string(value["owner"])
                    cache[mint] = program
                    return program
                last_error = RuntimeError("mint account not found")
            except Exception as exc:
                last_error = exc
        raise TokenProgramUnavailableError(
            f"Token program could not be resolved for {mint}: {last_error}"
        )

    async def get_token_largest_accounts(
        self, mint: str, *, timeout_seconds: float = 3.0
    ) -> list[tuple[str, int]]:
        """Returns the mint's largest token accounts as ``(address, raw_amount)``.

        Used for pre-buy holder screening (BUG-95). Goes straight to the RPC pool,
        so a failed lookup does not lower ``execution_health_score``.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenLargestAccounts",
            "params": [mint, {"commitment": "confirmed"}],
        }
        parsed = await self.rpc_pool.request(
            payload, max_retries=1, timeout_seconds=timeout_seconds
        )
        if not isinstance(parsed, dict) or "error" in parsed:
            raise RuntimeError(f"getTokenLargestAccounts error: {parsed}")
        value = (parsed.get("result") or {}).get("value")
        if not isinstance(value, list):
            raise RuntimeError(f"Unexpected getTokenLargestAccounts value: {parsed}")
        accounts: list[tuple[str, int]] = []
        for entry in value:
            if not isinstance(entry, dict):
                continue
            address = entry.get("address")
            try:
                amount = int(entry.get("amount") or 0)
            except (TypeError, ValueError):
                continue
            if isinstance(address, str) and address:
                accounts.append((address, amount))
        return accounts

    def tip_account_set(self) -> set[str]:
        """Every Jito tip account a tip may have been sent to."""
        accounts = set(JITO_TIP_ACCOUNTS)
        if self.jito_client is not None:
            accounts.update(str(a) for a in self.jito_client.tip_accounts or [])
        return accounts

    def wallet_token_accounts(self, mint: str) -> list[str]:
        """The wallet's ATA for ``mint`` under both token programs."""
        mint_pubkey = self._to_pubkey(mint)
        return [
            str(
                get_associated_token_address(
                    self.wallet, mint_pubkey, self._to_pubkey(program)
                )
            )
            for program in (TOKEN_PROGRAM_ID_STR, TOKEN_2022_PROGRAM_ID_STR)
        ]

    def modelled_priority_fee_lamports(self) -> int:
        """Priority fee the transaction builder attaches (compute price x limit)."""
        if self.compute_unit_limit <= 0:
            return 0
        unit_price = self.compute_unit_price_micro_lamports
        if unit_price is None:
            if self.priority_fee_lamports <= 0:
                return 0
            unit_price = int(
                (self.priority_fee_lamports * 1_000_000) / self.compute_unit_limit
            )
        return max(0, int(unit_price * self.compute_unit_limit / 1_000_000))

    def model_trade_costs(
        self, *, rent_lamports: int = 0, signature: str | None = None
    ) -> TransactionCosts:
        """Modelled costs of one trade for paper/dry-run accounting (FEAT-49).

        Uses the static ``jito_tip_lamports``; live trades may pay a higher
        dynamic tip, which is read from the transaction instead.
        """
        return model_transaction_costs(
            priority_fee_lamports=self.modelled_priority_fee_lamports(),
            tip_lamports=self.jito_tip_lamports if self.use_jito else 0,
            rent_lamports=rent_lamports,
            signature=signature,
        )

    async def get_transaction_costs(
        self,
        signature: str,
        mint: str,
        *,
        is_buy: bool,
        attempts: int = 4,
        delay_seconds: float = 0.5,
    ) -> TransactionCosts:
        """Fee, tip, rent and exact swap amount of a confirmed trade (FEAT-49).

        ``getTransaction`` can return ``null`` for a moment after confirmation, so
        it is polled a few times. Raises ``RuntimeError`` if it never appears.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "json",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
        last_error: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                parsed = await self.rpc_pool.request(
                    payload, max_retries=1, timeout_seconds=5.0
                )
                result = parsed.get("result") if isinstance(parsed, dict) else None
                if isinstance(result, dict):
                    return parse_transaction_costs(
                        result,
                        wallet=str(self.wallet),
                        is_buy=is_buy,
                        token_accounts=self.wallet_token_accounts(mint),
                        tip_accounts=self.tip_account_set(),
                        signature=signature,
                    )
                last_error = RuntimeError("transaction not found yet")
            except ValueError:
                raise
            except Exception as exc:
                last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(delay_seconds)
        raise RuntimeError(
            f"Transaction costs unavailable for {signature}: {last_error}"
        )

    async def get_ata_address(
        self,
        mint: str,
        owner: Optional[str] = None,
        token_program: Pubkey | str | None = None,
    ) -> str:
        owner_pubkey = self._to_pubkey(owner or str(self.wallet))
        mint_pubkey = self._to_pubkey(mint)
        prog = (
            self._to_pubkey(token_program)
            if token_program is not None
            else await self.get_token_program_for_mint(mint)
        )
        ata = get_associated_token_address(owner_pubkey, mint_pubkey, prog)
        return str(ata)

    async def get_ata_exists(
        self,
        mint: str,
        owner: Optional[str] = None,
        token_program: Pubkey | str | None = None,
    ) -> bool:
        owner_pubkey = owner or str(self.wallet)
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    owner_pubkey,
                    {"mint": mint},
                    {"encoding": "jsonParsed"},
                ],
            }
            parsed = await self._request_rpc_json(payload)
            accounts = (parsed.get("result") or {}).get("value", [])
            if isinstance(accounts, list) and len(accounts) > 0:
                return True
        except Exception:
            pass

        try:
            ata_addr = await self.get_ata_address(mint, owner_pubkey, token_program)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [ata_addr, {"encoding": "base64"}],
            }
            parsed = await self._request_rpc_json(payload)
            if (parsed.get("result") or {}).get("value") is not None:
                return True
        except Exception:
            pass

        return False

    def get_bonding_curve_pda(
        self, mint: str, token_program: Pubkey | str | None = None
    ) -> tuple[str, str]:
        self.is_valid_mint(mint)
        mint_pubkey = self._to_pubkey(mint)
        program_id = self._to_pubkey(PUMP_PROGRAM_ID)
        bonding_curve_pda, _ = Pubkey.find_program_address(
            [b"bonding-curve", bytes(mint_pubkey)], program_id
        )
        # The associated bonding curve is the curve's ATA: [owner, token_program, mint]
        # (BUG-93). Pass the mint's token program for Token-2022 mints.
        associated_curve_pda = get_associated_token_address(
            bonding_curve_pda,
            mint_pubkey,
            self._to_pubkey(token_program or TOKEN_PROGRAM_ID_STR),
        )
        return str(bonding_curve_pda), str(associated_curve_pda)

    def build_buy_instruction_v2(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        max_sol_cost: int,
        creator: str | None = None,
        base_token_program: Pubkey | str | None = None,
        is_mayhem_mode: bool = False,
    ) -> Instruction:
        self.is_valid_mint(mint)
        self.is_valid_pubkey(bonding_curve)
        mint_pubkey = self._to_pubkey(mint)
        bonding_curve_pubkey = self._to_pubkey(bonding_curve)
        user_pubkey = self.wallet
        pump_program = self._to_pubkey(PUMP_PROGRAM_ID)
        pump_fee_program = self._to_pubkey(PUMP_FEE_PROGRAM_ID)
        token_program = self._to_pubkey(TOKEN_PROGRAM_ID_STR)
        base_token_prog = (
            self._to_pubkey(base_token_program)
            if base_token_program is not None
            else token_program
        )
        fee_recipient = self._to_pubkey(
            MAYHEM_FEE_RECIPIENT if is_mayhem_mode else FEE_RECIPIENT
        )
        buyback_fee_recipient = self._to_pubkey(BUYBACK_FEE_RECIPIENT)
        system_program = self._to_pubkey(SYSTEM_PROGRAM_ID)
        event_authority = self._to_pubkey(EVENT_AUTHORITY)

        creator_pubkey = (
            self._to_pubkey(creator)
            if creator and creator != SYSTEM_PROGRAM_ID
            else user_pubkey
        )

        creator_vault, _ = Pubkey.find_program_address(
            [b"creator-vault", bytes(creator_pubkey)], pump_program
        )
        global_vol, _ = Pubkey.find_program_address(
            [b"global_volume_accumulator"], pump_program
        )
        user_vol, _ = Pubkey.find_program_address(
            [b"user_volume_accumulator", bytes(user_pubkey)], pump_program
        )
        fee_config, _ = Pubkey.find_program_address(
            [b"fee_config", FEE_CONFIG_KEY], pump_fee_program
        )
        bonding_curve_v2, _ = Pubkey.find_program_address(
            [b"bonding-curve-v2", bytes(mint_pubkey)], pump_program
        )

        assoc_base_curve = get_associated_token_address(
            bonding_curve_pubkey, mint_pubkey, base_token_prog
        )
        assoc_base_user = get_associated_token_address(
            user_pubkey, mint_pubkey, base_token_prog
        )

        data = BUY_DISCRIMINATOR + self._u64(token_amount) + self._u64(max_sol_cost)

        accounts = [
            AccountMeta(
                pubkey=self._to_pubkey(GLOBAL_STATE), is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=fee_recipient, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pubkey, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_pubkey, is_signer=False, is_writable=True),
            AccountMeta(pubkey=assoc_base_curve, is_signer=False, is_writable=True),
            AccountMeta(pubkey=assoc_base_user, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
            AccountMeta(pubkey=system_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=base_token_prog, is_signer=False, is_writable=False),
            AccountMeta(pubkey=creator_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=event_authority, is_signer=False, is_writable=False),
            AccountMeta(pubkey=pump_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=global_vol, is_signer=False, is_writable=False),
            AccountMeta(pubkey=user_vol, is_signer=False, is_writable=True),
            AccountMeta(pubkey=fee_config, is_signer=False, is_writable=False),
            AccountMeta(pubkey=pump_fee_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_v2, is_signer=False, is_writable=False),
            AccountMeta(
                pubkey=buyback_fee_recipient, is_signer=False, is_writable=True
            ),
        ]
        return Instruction(program_id=pump_program, accounts=accounts, data=data)

    def build_sell_instruction_v2(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        min_sol_output: int,
        creator: str | None = None,
        base_token_program: Pubkey | str | None = None,
        is_mayhem_mode: bool = False,
    ) -> Instruction:
        self.is_valid_mint(mint)
        self.is_valid_pubkey(bonding_curve)
        mint_pubkey = self._to_pubkey(mint)
        bonding_curve_pubkey = self._to_pubkey(bonding_curve)
        user_pubkey = self.wallet
        pump_program = self._to_pubkey(PUMP_PROGRAM_ID)
        pump_fee_program = self._to_pubkey(PUMP_FEE_PROGRAM_ID)
        token_program = self._to_pubkey(TOKEN_PROGRAM_ID_STR)
        base_token_prog = (
            self._to_pubkey(base_token_program)
            if base_token_program is not None
            else token_program
        )
        fee_recipient = self._to_pubkey(
            MAYHEM_FEE_RECIPIENT if is_mayhem_mode else FEE_RECIPIENT
        )
        buyback_fee_recipient = self._to_pubkey(BUYBACK_FEE_RECIPIENT)
        system_program = self._to_pubkey(SYSTEM_PROGRAM_ID)
        event_authority = self._to_pubkey(EVENT_AUTHORITY)

        creator_pubkey = (
            self._to_pubkey(creator)
            if creator and creator != SYSTEM_PROGRAM_ID
            else user_pubkey
        )

        creator_vault, _ = Pubkey.find_program_address(
            [b"creator-vault", bytes(creator_pubkey)], pump_program
        )
        fee_config, _ = Pubkey.find_program_address(
            [b"fee_config", FEE_CONFIG_KEY], pump_fee_program
        )
        bonding_curve_v2, _ = Pubkey.find_program_address(
            [b"bonding-curve-v2", bytes(mint_pubkey)], pump_program
        )

        assoc_base_curve = get_associated_token_address(
            bonding_curve_pubkey, mint_pubkey, base_token_prog
        )
        assoc_base_user = get_associated_token_address(
            user_pubkey, mint_pubkey, base_token_prog
        )

        data = SELL_DISCRIMINATOR + self._u64(token_amount) + self._u64(min_sol_output)

        accounts = [
            AccountMeta(
                pubkey=self._to_pubkey(GLOBAL_STATE), is_signer=False, is_writable=False
            ),
            AccountMeta(pubkey=fee_recipient, is_signer=False, is_writable=True),
            AccountMeta(pubkey=mint_pubkey, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_pubkey, is_signer=False, is_writable=True),
            AccountMeta(pubkey=assoc_base_curve, is_signer=False, is_writable=True),
            AccountMeta(pubkey=assoc_base_user, is_signer=False, is_writable=True),
            AccountMeta(pubkey=user_pubkey, is_signer=True, is_writable=True),
            AccountMeta(pubkey=system_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=creator_vault, is_signer=False, is_writable=True),
            AccountMeta(pubkey=base_token_prog, is_signer=False, is_writable=False),
            AccountMeta(pubkey=event_authority, is_signer=False, is_writable=False),
            AccountMeta(pubkey=pump_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=fee_config, is_signer=False, is_writable=False),
            AccountMeta(pubkey=pump_fee_program, is_signer=False, is_writable=False),
            AccountMeta(pubkey=bonding_curve_v2, is_signer=False, is_writable=False),
            AccountMeta(
                pubkey=buyback_fee_recipient, is_signer=False, is_writable=True
            ),
        ]
        return Instruction(program_id=pump_program, accounts=accounts, data=data)

    def build_buy_instruction(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        max_sol_cost: int,
        creator: str | None = None,
        base_token_program: Pubkey | str | None = None,
        is_mayhem_mode: bool = False,
    ) -> Instruction:
        return self.build_buy_instruction_v2(
            mint=mint,
            bonding_curve=bonding_curve,
            token_amount=token_amount,
            max_sol_cost=max_sol_cost,
            creator=creator,
            base_token_program=base_token_program,
            is_mayhem_mode=is_mayhem_mode,
        )

    def build_sell_instruction(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        min_sol_output: int,
        creator: str | None = None,
        base_token_program: Pubkey | str | None = None,
        is_mayhem_mode: bool = False,
    ) -> Instruction:
        return self.build_sell_instruction_v2(
            mint=mint,
            bonding_curve=bonding_curve,
            token_amount=token_amount,
            min_sol_output=min_sol_output,
            creator=creator,
            base_token_program=base_token_program,
            is_mayhem_mode=is_mayhem_mode,
        )

    def build_set_compute_unit_limit_instruction(
        self, units: int = 200_000
    ) -> Instruction:
        """Create ComputeBudget instruction to set max compute units."""
        data = bytes([2]) + units.to_bytes(4, byteorder="little", signed=False)
        return Instruction(
            program_id=self._to_pubkey(COMPUTE_BUDGET_PROGRAM_ID),
            accounts=[],
            data=data,
        )

    def build_set_compute_unit_price_instruction(
        self, micro_lamports: int
    ) -> Instruction:
        """Create ComputeBudget instruction to set priority fee per compute unit."""
        data = bytes([3]) + self._u64(micro_lamports)
        return Instruction(
            program_id=self._to_pubkey(COMPUTE_BUDGET_PROGRAM_ID),
            accounts=[],
            data=data,
        )

    def build_jito_tip_instruction(
        self, tip_lamports: int, tip_account: str | None = None
    ) -> Instruction:
        """Create transfer instruction sending Jito tip to validator tip address."""
        if tip_lamports <= 0:
            raise ValueError("Jito tip lamports must be positive")
        if tip_account is not None:
            target_account = tip_account
        elif self.jito_client is not None:
            target_account = self.jito_client.get_tip_account()
        else:
            target_account = JITO_TIP_ACCOUNTS[0]
        data = bytes([2, 0, 0, 0]) + self._u64(tip_lamports)
        accounts = [
            AccountMeta(pubkey=self.wallet, is_signer=True, is_writable=True),
            AccountMeta(
                pubkey=self._to_pubkey(target_account),
                is_signer=False,
                is_writable=True,
            ),
        ]
        return Instruction(
            program_id=self._to_pubkey(SYSTEM_PROGRAM_ID),
            accounts=accounts,
            data=data,
        )

    async def calculate_dynamic_jito_tip(
        self,
        trade_amount_sol: float = 0.0,
        conviction_score: float = 1.0,
    ) -> int:
        """Calculate dynamic Jito tip in Lamports based on trade amount and conviction."""
        if self.jito_client is not None:
            try:
                floor = await self.jito_client.fetch_tip_floor()
                return self.jito_client.calculate_tip_lamports(
                    trade_amount_sol=trade_amount_sol,
                    conviction_score=conviction_score,
                    tip_floor=floor,
                )
            except Exception:
                pass
        if self.jito_tip_lamports > 0:
            return self.jito_tip_lamports
        return self.jito_tip_config.default_tip_lamports

    async def get_bonding_curve_state(self, mint: str) -> dict[str, int | float | bool]:
        """Fetch and decode on-chain bonding curve account state directly from RPC."""
        bonding_curve_pda, _ = self.get_bonding_curve_pda(mint)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                bonding_curve_pda,
                {"encoding": "base64", "commitment": "confirmed"},
            ],
        }
        parsed = await self._request_rpc_json(payload)
        value = (parsed.get("result") or {}).get("value")
        if not value:
            raise NotPumpFunCurveError(
                f"Bonding curve account {bonding_curve_pda} not found on-chain"
            )
        owner = value.get("owner")
        if owner is not None and str(owner) != PUMP_PROGRAM_ID:
            # Anyone can fund a PDA address; only the program can own its data.
            raise NotPumpFunCurveError(
                f"Bonding curve account {bonding_curve_pda} of {mint} is owned by "
                f"{owner}, not the Pump.fun program"
            )
        raw_data_b64 = value.get("data", [""])[0]
        raw_bytes = base64.b64decode(raw_data_b64)
        state = self.decode_bonding_curve_data(raw_bytes)
        # Never price a position from a curve that decodes to nonsense.
        self._reject_non_standard_curve(mint, state)
        return state

    async def _fetch_trade_curve_state(self, mint: str) -> dict[str, Any]:
        """Fetches the bonding curve needed to build a trade.

        Raises instead of guessing: without the real creator the creator-vault PDA
        is wrong and the instruction fails on-chain with a seeds error (BUG-68).
        """
        bonding_curve_pda, _ = self.get_bonding_curve_pda(mint)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                bonding_curve_pda,
                {"encoding": "base64", "commitment": "confirmed"},
            ],
        }
        try:
            parsed = await self.rpc_pool.request(
                payload, max_retries=2, timeout_seconds=3.0
            )
            value = (parsed.get("result") or {}).get("value")
            curve_state = (
                self.decode_bonding_curve_data(
                    base64.b64decode(value.get("data", [""])[0])
                )
                if value
                else {}
            )
        except Exception as exc:
            raise CurveStateUnavailableError(
                f"Bonding curve fetch failed for {mint}: {exc}"
            ) from exc
        owner = value.get("owner") if value else None
        if owner is not None and str(owner) != PUMP_PROGRAM_ID:
            raise NotPumpFunCurveError(
                f"Bonding curve account {bonding_curve_pda} of {mint} is owned by "
                f"{owner}, not the Pump.fun program"
            )
        creator = str(curve_state.get("creator") or "")
        if not creator or creator == SYSTEM_PROGRAM_ID:
            raise CurveStateUnavailableError(
                f"Bonding curve creator could not be resolved for {mint}"
            )
        curve_state["creator"] = creator
        return curve_state

    @staticmethod
    def _live_curve_reserves(mint: str, curve_state: dict[str, Any]) -> tuple[int, int]:
        """Virtual (SOL, token) reserves read from the curve account.

        Raises instead of quoting against made-up initial-curve reserves when the
        account reports none (drained, graduated or undecodable curve): slippage
        must come from live reserves only (BUG-101).
        """
        v_sol = int(curve_state.get("virtual_sol_reserves", 0) or 0)
        v_token = int(curve_state.get("virtual_token_reserves", 0) or 0)
        if v_sol <= 0 or v_token <= 0:
            raise CurveStateUnavailableError(
                f"Bonding curve for {mint} reports no reserves "
                f"(sol={v_sol}, token={v_token}); refusing to quote"
            )
        return v_sol, v_token

    @staticmethod
    def _reject_non_standard_curve(mint: str, curve_state: dict[str, Any]) -> None:
        """Refuse to buy into a curve whose reserves fail the layout checks (BUG-104)."""
        anomaly = curve_reserve_anomaly(
            int(curve_state.get("virtual_sol_reserves", 0) or 0),
            int(curve_state.get("virtual_token_reserves", 0) or 0),
            int(curve_state.get("real_sol_reserves", 0) or 0),
            complete=bool(curve_state.get("complete", False)),
        )
        if anomaly:
            raise NonStandardCurveError(
                f"Non-standard bonding curve for {mint}: {anomaly}"
            )

    async def build_buy_tx(
        self,
        mint: str,
        bonding_curve: str,
        sol_amount: float,
        *,
        token_amount: Optional[int] = None,
        slippage_bps: Optional[int] = None,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        slippage_bps = (
            self.default_slippage_bps
            if slippage_bps is None
            else self.normalize_slippage_bps(slippage_bps)
        )
        lamports = self.sol_to_lamports(sol_amount)
        max_sol_cost = int((lamports * (10_000 + slippage_bps)) / 10_000)

        base_token_prog = await self.get_token_program_for_mint(mint)
        curve_state = await self._fetch_trade_curve_state(mint)
        self._reject_non_standard_curve(mint, curve_state)
        creator = curve_state["creator"]
        is_mayhem_mode = bool(curve_state.get("is_mayhem_mode", False))

        if token_amount is None or token_amount <= 0:
            v_sol, v_token = self._live_curve_reserves(mint, curve_state)
            token_amount = self.calculate_buy_tokens_out(
                lamports,
                v_sol,
                v_token,
                slippage_bps=slippage_bps,
                fee_bps=self.pump_fee_bps,
            )

        instructions = []
        ata_exists = False
        try:
            ata_exists = await self.get_ata_exists(mint, token_program=base_token_prog)
        except TypeError:
            try:
                ata_exists = await self.get_ata_exists(mint)
            except Exception:
                ata_exists = False
        except Exception:
            ata_exists = False

        if not ata_exists:
            # Idempotent create: a failed/stale lookup never breaks the buy (BUG-54).
            instructions.append(
                create_idempotent_associated_token_account(
                    payer=self.wallet,
                    owner=self.wallet,
                    mint=self._to_pubkey(mint),
                    token_program_id=base_token_prog,
                )
            )
        instructions.append(
            self.build_buy_instruction_v2(
                mint,
                bonding_curve,
                token_amount,
                max_sol_cost,
                creator=creator,
                base_token_program=base_token_prog,
                is_mayhem_mode=is_mayhem_mode,
            )
        )
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    async def build_sell_tx(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        *,
        min_sol_output: int | float = 0,
        slippage_bps: int | None = None,
        tip_lamports: Optional[int] = None,
        close_token_account: bool = False,
    ) -> VersionedTransaction:
        """Pump.fun bonding-curve sell.

        With ``close_token_account`` the wallet's token account is closed after the
        sell, refunding its ~0.002 SOL rent (BUG-96). Only pass it when
        ``token_amount`` is the whole balance: closing a non-empty account fails
        the whole transaction.
        """
        slippage_bps = self.normalize_slippage_bps(
            slippage_bps, self.default_slippage_bps
        )
        if isinstance(min_sol_output, float):
            min_sol_lamports = self.sol_to_lamports(min_sol_output)
        else:
            min_sol_lamports = int(min_sol_output)

        if min_sol_lamports < 0:
            raise ValueError("Minimum SOL output cannot be negative")

        base_token_prog = await self.get_token_program_for_mint(mint)
        curve_state = await self._fetch_trade_curve_state(mint)
        creator = curve_state["creator"]
        is_mayhem_mode = bool(curve_state.get("is_mayhem_mode", False))

        if min_sol_lamports <= 0:
            v_sol, v_token = self._live_curve_reserves(mint, curve_state)
            min_sol_lamports = self.calculate_sell_sol_out(
                token_amount,
                v_token,
                v_sol,
                slippage_bps=slippage_bps,
                fee_bps=self.pump_fee_bps,
            )
        else:
            min_sol_lamports = max(
                0, int((min_sol_lamports * (10_000 - slippage_bps)) / 10_000)
            )

        instructions = [
            self.build_sell_instruction_v2(
                mint,
                bonding_curve,
                token_amount,
                min_sol_lamports,
                creator=creator,
                base_token_program=base_token_prog,
                is_mayhem_mode=is_mayhem_mode,
            )
        ]
        if close_token_account:
            instructions.append(
                self._token_account_close_instruction(mint, base_token_prog)
            )
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    def _token_account_close_instruction(
        self, mint: str, token_program: Pubkey | str
    ) -> Instruction:
        """Close the wallet's (empty) token account, refunding its rent (BUG-96)."""
        program = self._to_pubkey(token_program)
        ata = get_associated_token_address(self.wallet, self._to_pubkey(mint), program)
        return close_account(
            CloseAccountParams(
                program_id=program,
                account=ata,
                dest=self.wallet,
                owner=self.wallet,
            )
        )

    def build_raydium_swap_instruction(
        self,
        pool_keys: RaydiumPoolKeys,
        amount_in_lamports: int,
        min_amount_out: int = 1,
        user_source_token_account: Optional[str] = None,
        user_destination_token_account: Optional[str] = None,
        *,
        is_buy: bool = True,
        coin_token_program: Pubkey | str | None = None,
    ) -> Instruction:
        """Construct Raydium AMM v4 swap instruction for this client wallet.

        Buys swap WSOL (pc) ATA -> token (coin) ATA; sells swap token ATA -> WSOL
        ATA (BUG-36).
        """
        pc_ata = str(
            get_associated_token_address(
                self.wallet, self._to_pubkey(pool_keys.pc_mint), TOKEN_PROGRAM_ID
            )
        )
        coin_ata = str(
            get_associated_token_address(
                self.wallet,
                self._to_pubkey(pool_keys.coin_mint),
                self._to_pubkey(coin_token_program or TOKEN_PROGRAM_ID_STR),
            )
        )
        default_source, default_dest = (
            (pc_ata, coin_ata) if is_buy else (coin_ata, pc_ata)
        )
        return build_raydium_swap_instruction(
            pool_keys=pool_keys,
            user_wallet=self.wallet,
            user_source_token_account=user_source_token_account or default_source,
            user_destination_token_account=(
                user_destination_token_account or default_dest
            ),
            amount_in_lamports=amount_in_lamports,
            min_amount_out=min_amount_out,
        )

    def _wsol_open_instructions(self, wsol_ata: Pubkey, lamports: int) -> list:
        """Create (idempotently) the WSOL ATA and optionally wrap ``lamports`` into it."""
        wsol_mint = self._to_pubkey(WSOL_MINT_STR)
        instructions: list = [
            create_idempotent_associated_token_account(
                payer=self.wallet, owner=self.wallet, mint=wsol_mint
            )
        ]
        if lamports > 0:
            instructions.append(
                transfer(
                    TransferParams(
                        from_pubkey=self.wallet, to_pubkey=wsol_ata, lamports=lamports
                    )
                )
            )
            instructions.append(
                sync_native(
                    SyncNativeParams(program_id=TOKEN_PROGRAM_ID, account=wsol_ata)
                )
            )
        return instructions

    def _wsol_close_instruction(self, wsol_ata: Pubkey) -> Instruction:
        """Close the WSOL ATA, unwrapping its lamports back to the wallet."""
        return close_account(
            CloseAccountParams(
                program_id=TOKEN_PROGRAM_ID,
                account=wsol_ata,
                dest=self.wallet,
                owner=self.wallet,
            )
        )

    async def _raydium_reserves(self, pool_keys: RaydiumPoolKeys) -> tuple[int, int]:
        """Returns (coin_reserve, pc_reserve) in raw units from the pool vaults."""
        reserves = []
        for vault in (
            pool_keys.pool_coin_token_account,
            pool_keys.pool_pc_token_account,
        ):
            parsed = await self._request_rpc_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTokenAccountBalance",
                    "params": [str(vault), {"commitment": "confirmed"}],
                }
            )
            value = (parsed.get("result") or {}).get("value") or {}
            if "amount" not in value:
                raise RuntimeError(f"Raydium vault balance unavailable: {vault}")
            reserves.append(int(value["amount"]))
        return reserves[0], reserves[1]

    async def build_raydium_buy_tx(
        self,
        pool_keys: RaydiumPoolKeys,
        sol_amount: float,
        *,
        slippage_bps: Optional[int] = None,
        min_amount_out: int = 1,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        """Construct a Raydium AMM buy: wrap SOL -> swap -> unwrap (BUG-51).

        ``min_amount_out`` is derived from live pool reserves and ``slippage_bps``
        unless the caller passes a stricter value.
        """
        lamports = self.sol_to_lamports(sol_amount)
        slippage = self.normalize_slippage_bps(slippage_bps, self.default_slippage_bps)
        coin_reserve, pc_reserve = await self._raydium_reserves(pool_keys)
        _, quoted_min_out = calculate_raydium_swap_out(
            lamports, pc_reserve, coin_reserve, slippage_bps=slippage
        )
        if quoted_min_out <= 0:
            raise RuntimeError("Raydium quote returned zero output")
        min_out = max(int(min_amount_out), quoted_min_out)

        coin_program = await self.get_token_program_for_mint(pool_keys.coin_mint)
        wsol_ata = get_associated_token_address(
            self.wallet, self._to_pubkey(WSOL_MINT_STR), TOKEN_PROGRAM_ID
        )
        instructions = self._wsol_open_instructions(wsol_ata, lamports)
        instructions.append(
            create_idempotent_associated_token_account(
                payer=self.wallet,
                owner=self.wallet,
                mint=self._to_pubkey(pool_keys.coin_mint),
                token_program_id=coin_program,
            )
        )
        instructions.append(
            self.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=lamports,
                min_amount_out=min_out,
                is_buy=True,
                coin_token_program=coin_program,
            )
        )
        instructions.append(self._wsol_close_instruction(wsol_ata))
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    async def build_raydium_sell_tx(
        self,
        pool_keys: RaydiumPoolKeys,
        token_amount: int,
        *,
        slippage_bps: Optional[int] = None,
        min_sol_output: int | float = 1,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        """Construct a Raydium AMM sell: token ATA -> WSOL ATA, then unwrap (BUG-36)."""
        if isinstance(min_sol_output, float):
            min_out = self.sol_to_lamports(min_sol_output)
        else:
            min_out = int(min_sol_output)
        if slippage_bps is not None:
            coin_reserve, pc_reserve = await self._raydium_reserves(pool_keys)
            _, quoted_min_out = calculate_raydium_swap_out(
                int(token_amount),
                coin_reserve,
                pc_reserve,
                slippage_bps=self.normalize_slippage_bps(slippage_bps),
            )
            min_out = max(min_out, quoted_min_out)
        coin_program = await self.get_token_program_for_mint(pool_keys.coin_mint)
        wsol_ata = get_associated_token_address(
            self.wallet, self._to_pubkey(WSOL_MINT_STR), TOKEN_PROGRAM_ID
        )
        instructions = self._wsol_open_instructions(wsol_ata, 0)
        instructions.append(
            self.build_raydium_swap_instruction(
                pool_keys=pool_keys,
                amount_in_lamports=int(token_amount),
                min_amount_out=max(1, min_out),
                is_buy=False,
                coin_token_program=coin_program,
            )
        )
        instructions.append(self._wsol_close_instruction(wsol_ata))
        return await self._build_tx_with_instructions(
            instructions, tip_lamports=tip_lamports
        )

    async def _build_tx_with_instructions(
        self,
        instructions,
        *,
        tip_lamports: Optional[int] = None,
    ) -> VersionedTransaction:
        tx_instructions = []
        if self.compute_unit_limit > 0:
            tx_instructions.append(
                self.build_set_compute_unit_limit_instruction(self.compute_unit_limit)
            )
        unit_price = self.compute_unit_price_micro_lamports
        if (
            unit_price is None
            and self.priority_fee_lamports > 0
            and self.compute_unit_limit > 0
        ):
            unit_price = int(
                (self.priority_fee_lamports * 1_000_000) / self.compute_unit_limit
            )
        if unit_price and unit_price > 0:
            tx_instructions.append(
                self.build_set_compute_unit_price_instruction(unit_price)
            )
        tx_instructions.extend(instructions)
        effective_tip = (
            tip_lamports if tip_lamports is not None else self.jito_tip_lamports
        )
        if effective_tip > 0:
            tx_instructions.append(self.build_jito_tip_instruction(effective_tip))

        blockhash = await self.get_latest_blockhash()
        account_keys = []
        for instruction in tx_instructions:
            for meta in instruction.accounts:
                if meta.pubkey not in account_keys:
                    account_keys.append(meta.pubkey)
        if self.wallet not in account_keys:
            account_keys.insert(0, self.wallet)
        else:
            account_keys.remove(self.wallet)
            account_keys.insert(0, self.wallet)
        from solders.hash import Hash

        blockhash_obj = (
            Hash.from_string(blockhash) if isinstance(blockhash, str) else blockhash
        )
        message = MessageV0.try_compile(
            self.wallet,
            tx_instructions,
            [],
            blockhash_obj,
        )
        signature = self.keypair.sign_message(bytes(message))
        return VersionedTransaction.populate(message, [signature])

    async def build_sol_transfer_tx(
        self, destination: str, lamports: int
    ) -> VersionedTransaction:
        """System transfer from the wallet (profit sweep, FEAT-42); no Jito tip."""
        if int(lamports) <= 0:
            raise ValueError("Transfer lamports must be positive")
        target = self._to_pubkey(destination)
        if target == self.wallet:
            raise ValueError("Refusing to transfer SOL to the wallet itself")
        instruction = transfer(
            TransferParams(
                from_pubkey=self.wallet, to_pubkey=target, lamports=int(lamports)
            )
        )
        return await self._build_tx_with_instructions([instruction], tip_lamports=0)

    async def transfer_sol(self, destination: str, lamports: int) -> str:
        """Sends ``lamports`` to ``destination`` over RPC; returns the signature."""
        tx = await self.build_sol_transfer_tx(destination, lamports)
        return await self.send_transaction(tx)

    async def send_jito_bundle(
        self,
        transactions: list[VersionedTransaction],
        *,
        endpoint_url: Optional[str] = None,
    ) -> str:
        """Submit a bundle of versioned transactions to Jito Block Engine."""
        url = (
            endpoint_url
            or self.jito_block_engine_url
            or "https://mainnet.block-engine.jito.wtf/api/v1/bundles"
        )
        encoded_txs = [
            base64.b64encode(bytes(tx)).decode("utf-8") for tx in transactions
        ]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendBundle",
            "params": [encoded_txs, {"encoding": "base64"}],
        }
        timeout = aiohttp.ClientTimeout(total=15.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url, json=payload, headers={"Content-Type": "application/json"}
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Jito bundle submission failed (HTTP {resp.status}): {body[:500]}"
                    )
                parsed = json.loads(body)
                result = parsed.get("result")
                if not result:
                    raise RuntimeError(f"Invalid Jito bundle response: {parsed}")
                return str(result)

    async def send_jito_bundle_with_fallback(
        self,
        transactions: list[VersionedTransaction],
        *,
        timeout_seconds: Optional[float] = None,
    ) -> str:
        """Submit transactions via Jito bundle with confirmation polling and direct RPC fallback."""
        if not transactions:
            raise ValueError("Cannot submit empty transaction list as bundle")

        tx = transactions[0]
        tx_sig = str(tx.signatures[0]) if tx.signatures else ""
        timeout = timeout_seconds or self.jito_confirmation_timeout

        try:
            if self.jito_client is not None:
                bundle_id = await self.jito_client.send_bundle(transactions)
                status = await self.jito_client.wait_for_bundle_confirmation(
                    bundle_id, timeout_seconds=timeout
                )
                if status.is_landed:
                    self.execution_health_score = min(
                        100.0, self.execution_health_score + 5.0
                    )
                    return tx_sig
                if status.is_failed:
                    raise RuntimeError(f"Jito bundle {bundle_id} failed: {status.err}")
                # Unknown/pending is not a fill: fall through to the RPC fallback,
                # which re-sends the same signed tx (deduplicated by signature).
                raise TimeoutError(f"Jito bundle {bundle_id} not landed within timeout")
            else:
                bundle_id = await self.send_jito_bundle(transactions)
                confirmed = await self.confirm_transaction(
                    tx_sig, max_retries=max(1, int(timeout))
                )
                if confirmed:
                    return tx_sig
                raise TimeoutError(f"Bundle {bundle_id} not confirmed within timeout")
        except Exception:
            if not self.jito_fallback_to_rpc:
                raise
            self.failed_execution_attempts += 1
            self.execution_health_score = max(0.0, self.execution_health_score - 5.0)
            # Fast fallback to high-priority direct RPC submission
            return await self.send_transaction(tx)

    async def send_transaction(self, tx: VersionedTransaction) -> str:
        async with self._execution_lock:
            encoded_tx = base64.b64encode(bytes(tx)).decode("utf-8")
            result: Any = None
            if self.rpc_pool is not None and self.rpc_pool.endpoint_count > 1:
                result = await self.rpc_pool.broadcast_transaction(
                    encoded_tx,
                    skip_preflight=True,
                    preflight_commitment="confirmed",
                )
            else:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "sendTransaction",
                    "params": [
                        encoded_tx,
                        {
                            "skipPreflight": True,
                            "preflightCommitment": "confirmed",
                            "encoding": "base64",
                            "maxRetries": 3,
                        },
                    ],
                }
                parsed = await self._request_rpc_json(payload)
                result = parsed.get("result")
            if not isinstance(result, str) or len(result) < 20:
                raise RuntimeError(f"Invalid sendTransaction result: {result}")
            self.execution_health_score = min(100.0, self.execution_health_score + 5.0)
            return result

    async def confirm_transaction(
        self, signature: str, max_retries: int = 20, interval: float = 1.0
    ) -> bool:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignatureStatuses",
            "params": [[signature], {"searchTransactionHistory": True}],
        }
        for _ in range(max_retries):
            try:
                parsed = await self._request_rpc_json(payload, timeout_seconds=5.0)
                result = (parsed.get("result") or {}).get("value")
                if not result:
                    await asyncio.sleep(interval)
                    continue
                status = result[0]
                if not status:
                    await asyncio.sleep(interval)
                    continue
                confirmation_status = status.get("confirmationStatus")
                if confirmation_status in {
                    "processed",
                    "confirmed",
                    "finalized",
                }:
                    if status.get("err") is None:
                        return True
                    return False
            except RuntimeError as exc:
                if "On-chain transaction failed" in str(exc):
                    raise
            except Exception:
                pass
            await asyncio.sleep(interval)
        return False

    async def buy(
        self,
        mint: str,
        bonding_curve: str,
        sol_amount: float,
        *,
        token_amount: Optional[int] = None,
        slippage_bps: Optional[int] = None,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
    ) -> str:
        should_jito = self.use_jito if use_jito is None else use_jito
        tip_lamports = None
        if should_jito:
            tip_lamports = await self.calculate_dynamic_jito_tip(
                trade_amount_sol=sol_amount, conviction_score=conviction_score
            )
        tx = await self.build_buy_tx(
            mint,
            bonding_curve,
            sol_amount,
            token_amount=token_amount,
            slippage_bps=slippage_bps,
            tip_lamports=tip_lamports,
        )
        if should_jito:
            return await self.send_jito_bundle_with_fallback([tx])
        return await self.send_transaction(tx)

    async def raydium_buy(
        self,
        pool_keys: RaydiumPoolKeys,
        sol_amount: float,
        *,
        slippage_bps: Optional[int] = None,
        min_amount_out: int = 1,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
    ) -> str:
        """Execute a Raydium AMM v4 swap buy using Jito bundle or standard transaction."""
        should_jito = self.use_jito if use_jito is None else use_jito
        tip_lamports = None
        if should_jito:
            tip_lamports = await self.calculate_dynamic_jito_tip(
                trade_amount_sol=sol_amount, conviction_score=conviction_score
            )
        tx = await self.build_raydium_buy_tx(
            pool_keys=pool_keys,
            sol_amount=sol_amount,
            slippage_bps=slippage_bps,
            min_amount_out=min_amount_out,
            tip_lamports=tip_lamports,
        )
        if should_jito:
            return await self.send_jito_bundle_with_fallback([tx])
        return await self.send_transaction(tx)

    async def swap_raydium(
        self,
        pool_keys: RaydiumPoolKeys,
        amount_in: int,
        *,
        is_buy: bool = True,
        min_amount_out: int = 1,
        slippage_bps: Optional[int] = None,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
    ) -> str:
        """Execute a Raydium AMM v4 swap (buy or sell)."""
        if is_buy:
            sol_amount = float(amount_in) / 1_000_000_000.0
            return await self.raydium_buy(
                pool_keys=pool_keys,
                sol_amount=sol_amount,
                slippage_bps=slippage_bps,
                min_amount_out=min_amount_out,
                use_jito=use_jito,
                conviction_score=conviction_score,
            )
        else:
            should_jito = self.use_jito if use_jito is None else use_jito
            tip_lamports = None
            if should_jito:
                tip_lamports = await self.calculate_dynamic_jito_tip(
                    trade_amount_sol=0.01, conviction_score=conviction_score
                )
            tx = await self.build_raydium_sell_tx(
                pool_keys=pool_keys,
                token_amount=amount_in,
                slippage_bps=slippage_bps,
                min_sol_output=min_amount_out,
                tip_lamports=tip_lamports,
            )
            if should_jito:
                return await self.send_jito_bundle_with_fallback([tx])
            return await self.send_transaction(tx)

    async def sell(
        self,
        mint: str,
        bonding_curve: str,
        token_amount: int,
        *,
        min_sol_output: int | float = 0,
        slippage_bps: Optional[int] = None,
        use_jito: Optional[bool] = None,
        conviction_score: float = 1.0,
        close_token_account: bool = False,
    ) -> str:
        should_jito = self.use_jito if use_jito is None else use_jito
        tip_lamports = None
        if should_jito:
            approx_sol = (
                (float(min_sol_output) / 1_000_000_000) if min_sol_output > 0 else 0.0
            )
            tip_lamports = await self.calculate_dynamic_jito_tip(
                trade_amount_sol=approx_sol, conviction_score=conviction_score
            )
        tx = await self.build_sell_tx(
            mint,
            bonding_curve,
            token_amount,
            min_sol_output=min_sol_output,
            slippage_bps=slippage_bps,
            tip_lamports=tip_lamports,
            close_token_account=close_token_account,
        )
        if should_jito:
            return await self.send_jito_bundle_with_fallback([tx])
        return await self.send_transaction(tx)

    async def close(self) -> None:
        """Close external client connections including Jito client and RPC pool."""
        if self.jito_client is not None:
            await self.jito_client.close()
        if self.rpc_pool is not None:
            await self.rpc_pool.close()

    async def get_token_balance(self, mint: str, owner: Optional[str] = None) -> int:
        """Return the token balance for the wallet ATA for a given mint, in raw token units.

        ``0`` is returned only when the RPC confirms there is no balance. Any RPC or
        parse failure raises :class:`TokenBalanceUnavailableError` so callers can
        retry instead of treating the position as dust (BUG-35).
        """
        owner_pubkey = owner or str(self.wallet)
        errors: list[str] = []
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountsByOwner",
                "params": [
                    owner_pubkey,
                    {"mint": mint},
                    {"encoding": "jsonParsed", "commitment": "confirmed"},
                ],
            }
            parsed = await self._request_rpc_json(payload)
            if "error" in parsed or not isinstance(parsed.get("result"), dict):
                raise RuntimeError(f"getTokenAccountsByOwner error: {parsed}")
            accounts = parsed["result"].get("value")
            if not isinstance(accounts, list):
                raise RuntimeError(
                    f"Unexpected getTokenAccountsByOwner value: {parsed}"
                )
            if not accounts:
                return 0
            for acc in accounts:
                info = (
                    ((acc.get("account") or {}).get("data") or {})
                    .get("parsed", {})
                    .get("info", {})
                )
                token_amount_obj = info.get("tokenAmount", {})
                if "amount" in token_amount_obj:
                    return int(token_amount_obj["amount"])
            raise RuntimeError("Token account has no parsed amount")
        except Exception as exc:
            errors.append(str(exc))

        try:
            ata = await self.get_ata_address(mint, owner_pubkey)
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenAccountBalance",
                "params": [ata, {"commitment": "confirmed"}],
            }
            parsed = await self._request_rpc_json(payload)
            error = parsed.get("error")
            if isinstance(error, dict) and "could not find account" in str(
                error.get("message", "")
            ):
                return 0
            value = (parsed.get("result") or {}).get("value")
            if isinstance(value, dict) and "amount" in value:
                return int(value["amount"])
            errors.append(f"getTokenAccountBalance returned no amount: {parsed}")
        except Exception as exc:
            errors.append(str(exc))
        raise TokenBalanceUnavailableError(
            f"Token balance unavailable for {mint}: {'; '.join(errors)}"
        )
