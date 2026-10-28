"""Pump.fun bonding-curve state, PDA derivation, instruction and trade builders."""

import base64
import logging
import time
from collections.abc import Sequence
from typing import Any, Optional

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.models import CloseAccountParams
from spl.token.instructions import (
    close_account,
    create_idempotent_associated_token_account,
    get_associated_token_address,
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
from .execution_types import (
    PUMP_PROGRAM_ID,
    GET_MULTIPLE_ACCOUNTS_LIMIT,
    GLOBAL_STATE,
    FEE_RECIPIENT,
    MAYHEM_FEE_RECIPIENT,
    BUYBACK_FEE_RECIPIENT,
    PUMP_FEE_PROGRAM_ID,
    SYSTEM_PROGRAM_ID,
    EVENT_AUTHORITY,
    TOKEN_PROGRAM_ID_STR,
    WSOL_MINT_STR,
    BUY_DISCRIMINATOR,
    SELL_DISCRIMINATOR,
    FEE_CONFIG_KEY,
    CurveStateUnavailableError,
    NonStandardCurveError,
    CurveAccountMissingError,
    NotPumpFunCurveError,
)
from .fee_config import FeeConfig, bonding_curve_fee_bps, decode_fee_config
from .transport import TransactionTransportMixin

# BondingCurve.quote_mint (BUG-124): zeroed or WSOL means the curve trades for SOL.
CURVE_QUOTE_MINT_START = 83
CURVE_QUOTE_MINT_END = 115
SOL_QUOTE_MINTS = frozenset({SYSTEM_PROGRAM_ID, WSOL_MINT_STR})
# The fee schedule changes rarely; re-read it at most this often (BUG-138).
FEE_CONFIG_TTL_SECONDS = 600.0
TOTAL_MINT_SUPPLY_RAW = 1_000_000_000_000_000

logger = logging.getLogger(__name__)


class PumpFunCurveMixin(TransactionTransportMixin):
    """Pump.fun bonding-curve reads plus buy/sell instruction and transaction builders."""

    _fee_config_cache: tuple[float, FeeConfig] | None = None

    @staticmethod
    def fee_config_address() -> str:
        """The Pump fee program's ``fee_config`` PDA for the Pump program."""
        pda, _ = Pubkey.find_program_address(
            [b"fee_config", FEE_CONFIG_KEY], Pubkey.from_string(PUMP_FEE_PROGRAM_ID)
        )
        return str(pda)

    async def get_pump_fee_config(
        self, *, max_age_seconds: float = FEE_CONFIG_TTL_SECONDS
    ) -> FeeConfig | None:
        """The current bonding-curve fee tiers from chain, cached (BUG-138).

        ``None`` when the account cannot be read or decoded; callers then keep
        ``pump_fee_bps``.
        """
        cached = self._fee_config_cache
        now = time.monotonic()
        if cached is not None and now - cached[0] < max_age_seconds:
            return cached[1]
        address = self.fee_config_address()
        try:
            parsed = await self._request_rpc_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [address, {"encoding": "base64"}],
                }
            )
            value = (parsed.get("result") or {}).get("value")
            if not value:
                raise ValueError(f"fee config {address} not found")
            owner = value.get("owner")
            if owner is not None and str(owner) != PUMP_FEE_PROGRAM_ID:
                raise ValueError(f"fee config {address} is owned by {owner}")
            config = decode_fee_config(base64.b64decode(value.get("data", [""])[0]))
        except Exception as exc:
            logger.warning("Pump.fun fee config unavailable: %s", exc)
            return cached[1] if cached is not None else None
        self._fee_config_cache = (now, config)
        return config

    def curve_fee_bps(self, virtual_sol_lamports: int, virtual_token_raw: int) -> int:
        """Fee a trade on this curve pays: the cached tier, else ``pump_fee_bps``."""
        cached = self._fee_config_cache
        if cached is None or virtual_sol_lamports <= 0 or virtual_token_raw <= 0:
            return int(self.pump_fee_bps)
        try:
            return bonding_curve_fee_bps(
                cached[1],
                virtual_sol_lamports,
                virtual_token_raw,
                TOTAL_MINT_SUPPLY_RAW,
            )
        except ValueError:
            return int(self.pump_fee_bps)

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
          82..83: is_cashback_coin (bool)
          83..115: quote_mint (Pubkey; all zeros on SOL-quoted curves)

        ``quote_mint`` is ``None`` on accounts too short to carry it (older
        curves are SOL-quoted).
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
        quote_mint = None
        if len(data) >= CURVE_QUOTE_MINT_END:
            quote_mint = str(
                Pubkey.from_bytes(data[CURVE_QUOTE_MINT_START:CURVE_QUOTE_MINT_END])
            )

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
            "quote_mint": quote_mint,
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
            raise CurveAccountMissingError(
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

    async def get_bonding_curve_states(
        self,
        mints: Sequence[str],
        *,
        rejected: dict[str, str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> dict[str, dict[str, int | float | bool]]:
        """Batch-read bonding curves with ``getMultipleAccounts`` (FEAT-51).

        Reads at most 100 accounts per call. Only curves that exist, are owned by
        the Pump.fun program (BUG-108) and pass the reserve sanity checks
        (BUG-104) are returned; every other mint is written to ``rejected`` with a
        reason (``missing``, ``not_pump_fun``, ``decode_error``, ``non_standard``).
        An RPC failure raises ``RuntimeError`` so the caller can back off.
        """
        unique = list(dict.fromkeys(str(m) for m in mints if m))
        states: dict[str, dict[str, int | float | bool]] = {}
        for start in range(0, len(unique), GET_MULTIPLE_ACCOUNTS_LIMIT):
            chunk = unique[start : start + GET_MULTIPLE_ACCOUNTS_LIMIT]
            pdas = [self.get_bonding_curve_pda(mint)[0] for mint in chunk]
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getMultipleAccounts",
                "params": [pdas, {"encoding": "base64", "commitment": "confirmed"}],
            }
            parsed = await self._request_rpc_json(
                payload, max_retries=1, timeout_seconds=timeout_seconds
            )
            values = (parsed.get("result") or {}).get("value") or []
            for index, mint in enumerate(chunk):
                value = values[index] if index < len(values) else None
                reason = None
                state: dict[str, Any] = {}
                if not value:
                    reason = "missing"
                elif str(value.get("owner") or PUMP_PROGRAM_ID) != PUMP_PROGRAM_ID:
                    reason = "not_pump_fun"
                else:
                    try:
                        raw = base64.b64decode((value.get("data") or [""])[0])
                        state = self.decode_bonding_curve_data(raw)
                        self._reject_non_standard_curve(mint, state)
                    except NonStandardCurveError:
                        reason = "non_standard"
                    except Exception:
                        reason = "decode_error"
                if reason is None:
                    states[mint] = state
                elif rejected is not None:
                    rejected[mint] = reason
        return states

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
        """Refuse to buy into a curve whose reserves fail the layout checks (BUG-104).

        A curve quoted in anything but SOL (e.g. USDC) is refused too: every
        reserve and price in this bot is in lamports (BUG-124).
        """
        quote_mint = curve_state.get("quote_mint")
        if quote_mint and str(quote_mint) not in SOL_QUOTE_MINTS:
            raise NonStandardCurveError(
                f"Non-standard bonding curve for {mint}: quote mint {quote_mint} is not SOL"
            )
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
                fee_bps=self.curve_fee_bps(v_sol, v_token),
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
                fee_bps=self.curve_fee_bps(v_sol, v_token),
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
        should_jito, tip_lamports = await self.resolve_trade_tip(
            is_buy=True,
            trade_amount_sol=sol_amount,
            conviction_score=conviction_score,
            use_jito=use_jito,
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
        approx_sol = (
            (float(min_sol_output) / 1_000_000_000) if min_sol_output > 0 else 0.0
        )
        should_jito, tip_lamports = await self.resolve_trade_tip(
            is_buy=False,
            trade_amount_sol=approx_sol,
            conviction_score=conviction_score,
            use_jito=use_jito,
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
