"""Execution client core: wallet, RPC access, shared helpers and account queries."""

import asyncio
from typing import Any

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.instructions import (
    get_associated_token_address,
)

from trading_pump.infra.rpc_pool import (
    RpcConnectionPool,
)

from .execution_types import (
    PUMP_DEFAULT_FEE_BPS,
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
    TokenBalanceUnavailableError,
    TokenProgramUnavailableError,
)
from .jito import (
    JITO_BLOCK_ENGINE_ENDPOINTS,
    JitoClient,
    JitoTipConfig,
)


class ExecutionClientBase:
    """Wallet, RPC pool, Jito settings and read-only account queries."""

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

        This is intentionally lightweight and reusable by the bot when a transaction
        result
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
        """Return True if a partial fill is material enough that it should be re-
        evaluated.
        """
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
    def _decode_keypair(private_key_b58: str) -> Keypair:
        from trading_pump.config.env import decode_keypair

        return decode_keypair(private_key_b58)

    def __init__(
        self,
        private_key_b58: str,
        rpc_url: str | None = None,
        *,
        rpc_pool: RpcConnectionPool | None = None,
        rpc_urls: list[str] | tuple[str, ...] | None = None,
        priority_fee_lamports: int = 5000,
        compute_unit_limit: int = 200_000,
        compute_unit_price_micro_lamports: int | None = None,
        jito_tip_lamports: int = 0,
        jito_block_engine_url: str | None = None,
        use_jito: bool = False,
        jito_fallback_to_rpc: bool = True,
        jito_confirmation_timeout: float = 12.0,
        jito_client: JitoClient | None = None,
        jito_tip_config: JitoTipConfig | None = None,
        default_slippage_bps: int = 500,
        jito_entry_tip_lamports: int | None = None,
        jito_exit_tip_lamports: int | None = None,
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
        # Fixed per-side tips for the entry/exit tip experiment; ``None`` keeps the
        # shared tip and 0 sends that side over plain RPC without a tip.
        self.jito_entry_tip_lamports = jito_entry_tip_lamports
        self.jito_exit_tip_lamports = jito_exit_tip_lamports
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
        self.jito_client: JitoClient | None = jito_client
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

    async def _get_accounts(
        self,
        addresses: list[str],
        *,
        max_retries: int = 2,
        timeout_seconds: float = 5.0,
    ) -> list[dict[str, Any] | None]:
        """``getMultipleAccounts``: one entry per address, ``None`` for an
        account that does not exist. A failed read raises (BUG-159)."""
        parsed = await self._request_rpc_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [
                    addresses,
                    {"encoding": "base64", "commitment": "confirmed"},
                ],
            },
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        # An answer that is not a list of accounts is a failed read, not a
        # list of missing accounts (BUG-159): a JSON-RPC error the pool hands
        # back (bad params, a wrong cluster's method set) must reach the log.
        if "error" in parsed:
            error = parsed.get("error")
            detail = (
                error
                if not isinstance(error, dict)
                else (f"[{error.get('code')}] {str(error.get('message', ''))[:200]}")
            )
            raise RuntimeError(f"getMultipleAccounts failed: {detail}")
        result = parsed.get("result")
        values = result.get("value") if isinstance(result, dict) else None
        if not isinstance(values, list):
            raise RuntimeError(
                f"getMultipleAccounts returned no account list: {result!r}"[:300]
            )
        return [
            values[index] if index < len(values) else None
            for index in range(len(addresses))
        ]

    async def get_signatures_for_address(
        self,
        address: str,
        *,
        limit: int,
        max_retries: int = 2,
        timeout_seconds: float = 5.0,
    ) -> list[dict[str, Any]]:
        """``getSignaturesForAddress``, newest first, at most ``limit``
        (FEAT-80: a pool's history tells when it was created). A failed read
        raises, as ``_get_accounts`` does (BUG-159)."""
        parsed = await self._request_rpc_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSignaturesForAddress",
                "params": [address, {"limit": int(limit), "commitment": "confirmed"}],
            },
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )
        result = parsed.get("result")
        if "error" in parsed or not isinstance(result, list):
            raise RuntimeError(
                f"getSignaturesForAddress failed: {parsed.get('error', result)!r}"[:300]
            )
        return [entry for entry in result if isinstance(entry, dict)]

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
            and ExecutionClientBase.is_valid_pubkey(value)
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

    async def get_balance_sol(self) -> float:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [str(self.wallet)],
        }
        parsed = await self._request_rpc_json(payload)
        result = parsed.get("result")
        value = result.get("value") if isinstance(result, dict) else None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            # An answer without a balance is not a balance of 0 (BUG-158): a
            # live run's day would start from it (BUG-130).
            raise RuntimeError(f"getBalance returned no balance: {result!r}")
        return value / 1_000_000_000.0

    async def get_wallet_balance_sol(self) -> float:
        """Alias for get_balance_sol for backward compatibility."""
        return await self.get_balance_sol()

    async def get_token_program_for_mint(self, mint: str) -> Pubkey:
        """Query mint account to determine if it uses Token-2022 or legacy SPL Token
        program.

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
        return [
            account
            for account in map(self._largest_account_entry, value)
            if account is not None
        ]

    @staticmethod
    def _largest_account_entry(entry: Any) -> tuple[str, int] | None:
        """``(address, raw_amount)`` of one ``getTokenLargestAccounts`` entry."""
        if not isinstance(entry, dict):
            return None
        address = entry.get("address")
        try:
            amount = int(entry.get("amount") or 0)
        except (TypeError, ValueError):
            return None
        if isinstance(address, str) and address:
            return address, amount
        return None

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

    async def get_ata_address(
        self,
        mint: str,
        owner: str | None = None,
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
        owner: str | None = None,
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

    async def close(self) -> None:
        """Close external client connections including Jito client and RPC pool."""
        if self.jito_client is not None:
            await self.jito_client.close()
        if self.rpc_pool is not None:
            await self.rpc_pool.close()

    async def _balance_by_owner(self, mint: str, owner: str) -> int:
        """The balance from ``getTokenAccountsByOwner``; raises when unknown."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                owner,
                {"mint": mint},
                {"encoding": "jsonParsed", "commitment": "confirmed"},
            ],
        }
        parsed = await self._request_rpc_json(payload)
        if "error" in parsed or not isinstance(parsed.get("result"), dict):
            raise RuntimeError(f"getTokenAccountsByOwner error: {parsed}")
        accounts = parsed["result"].get("value")
        if not isinstance(accounts, list):
            raise RuntimeError(f"Unexpected getTokenAccountsByOwner value: {parsed}")
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

    async def _balance_of_ata(self, mint: str, owner: str) -> tuple[int | None, str]:
        """The ATA's balance from ``getTokenAccountBalance`` (0 when the RPC
        says the account does not exist), or ``None`` and why not."""
        ata = await self.get_ata_address(mint, owner)
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
            return 0, ""
        value = (parsed.get("result") or {}).get("value")
        if isinstance(value, dict) and "amount" in value:
            return int(value["amount"]), ""
        return None, f"getTokenAccountBalance returned no amount: {parsed}"

    async def get_token_balance(self, mint: str, owner: str | None = None) -> int:
        """Return the token balance for the wallet ATA for a given mint, in raw token
        units.

        ``0`` is returned only when the RPC confirms there is no balance. Any RPC or
        parse failure raises :class:`TokenBalanceUnavailableError` so callers can
        retry instead of treating the position as dust (BUG-35).
        """
        owner_pubkey = owner or str(self.wallet)
        errors: list[str] = []
        try:
            return await self._balance_by_owner(mint, owner_pubkey)
        except Exception as exc:
            errors.append(str(exc))
        try:
            amount, problem = await self._balance_of_ata(mint, owner_pubkey)
            if amount is not None:
                return amount
            errors.append(problem)
        except Exception as exc:
            errors.append(str(exc))
        raise TokenBalanceUnavailableError(
            f"Token balance unavailable for {mint}: {'; '.join(errors)}"
        )
