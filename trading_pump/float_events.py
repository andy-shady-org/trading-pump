"""Float's on-chain records (FEAT-179): what the logs and accounts say.

Float (floatlaunch.xyz) launches coins on Raydium LaunchLab bonding curves,
and a curve that fills migrates to a Raydium CPMM pool. Everything here is
decoded from bytes and checked against mainnet before it was built
(2026-11-09; ``docs/dev/DONE.md``, FEAT-179):

* **LaunchLab's events** (its on-chain Anchor IDL, ``raydium_launchpad``
  0.2.0): ``TradeEvent`` (one per curve trade) and ``PoolCreateEvent`` (one
  per launch), logged as ``Program data:``. On 1,597 trades of 30 Float
  curves, every event's amounts matched its reserves and fees, the quote
  vault moved by the quote reserve's change plus the protocol fee, and the
  base vault by the base reserve's change.
* **Float's own launch event** (no IDL is published): the coin's mint, its
  quote mint, the curve, the launching signer, a second key (the signer
  again on every launch read) and the symbol. Its other events (fee claims,
  holder payouts, harvests) are kept as bytes with their discriminator.
* **CPMM's ``SwapEvent``**: on 656 swaps of 8 Float graduates' pools, the
  input vault rose by ``input_amount`` and the output vault fell by
  ``output_amount``.
* **Accounts:** a LaunchLab pool (429 bytes), a LaunchLab platform config
  (its fee rates), Float's config (the platform list), a CPMM pool (637
  bytes: vaults, mints and the fees held in the vaults).
* **The migration:** LaunchLab's ``migrate_to_cpswap`` instruction, whose
  accounts name the curve, the coin, the CPMM pool and its vaults.

A decoder answers ``None`` for bytes it does not recognise, never a guess.
"""

from __future__ import annotations

import base64
import binascii
import struct
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import base58

FLOAT_PROGRAM_ID = "3KguFi7YYzLgttG46fRism16CfcuNCkDh6U7td9JTqxX"
FLOAT_CONFIG = "AgaKFP4SfEeeM4r4GcSWBwpEAbfHh7wLkJGHqpWrLBQV"
LAUNCHLAB_PROGRAM_ID = "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"
CPMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
# Float's three platform configs on 2026-11-09 (the fee a side): used until
# the config account is read, and when it cannot be.
FLOAT_PLATFORMS: tuple[str, ...] = (
    "2TDPJJPV6nvTEqXABxrqno6Uzpipxxvh1zjLN3SMYn69",  # 1.0%
    "7paQR4MLZcGdG8ZYAyj9Qu2UsJgXmNVQGha7g1gim1sG",  # 2.0%
    "CKpEUk5SRk8CUNhhxaVPKtzKUKLgQe2tQHPH2eXWtaGR",  # 2.5%
)
TRADE_EVENT = bytes.fromhex("bddb7fd34ee661ee")
POOL_CREATE_EVENT = bytes.fromhex("97d7e20976a173ae")
FLOAT_LAUNCH_EVENT = bytes.fromhex("3b26bee621225914")
CPMM_SWAP_EVENT = bytes.fromhex("40c6cde8260871e2")
MIGRATE_TO_CPSWAP = bytes.fromhex("885cc8671cda908c")
# Float's instructions, as its logs name them.
LAUNCH_INSTRUCTIONS = frozenset({"Launch", "LaunchKeyed"})
FEE_INSTRUCTIONS = frozenset(
    {"ClaimCoinFees", "ClaimDevFees", "PayHolders", "Harvest", "HarvestGraduated"}
)
MIGRATE_INSTRUCTION = "MigrateToCpswap"
TRADE_DIRECTIONS = ("buy", "sell")
POOL_STATUSES = ("fund", "migrate", "trade")
LAUNCHLAB_POOL_SIZE = 429
CPMM_POOL_SIZE = 637
# LaunchLab's protocol fee (1e-6 units), the same on every platform.
PROTOCOL_FEE_RATE = 2_500
FEE_RATE_DENOMINATOR = 1_000_000
LOG_TRUNCATED = "Log truncated"

_INVOKE = " invoke ["
_DATA = "Program data: "
_LOG_INSTRUCTION = "Program log: Instruction: "


def pubkey_at(raw: bytes, offset: int) -> str:
    return base58.b58encode(raw[offset : offset + 32]).decode("ascii")


@dataclass(frozen=True)
class LogRecords:
    """One transaction's logs, read: each program's ``Program data:``
    payloads and instruction names, in order."""

    data: tuple[tuple[str, bytes], ...]
    instructions: tuple[tuple[str, str], ...]
    truncated: bool = False

    def data_of(self, program: str, discriminator: bytes) -> list[bytes]:
        return [
            payload
            for owner, payload in self.data
            if owner == program and payload[:8] == discriminator
        ]

    def instructions_of(self, program: str) -> list[str]:
        return [name for owner, name in self.instructions if owner == program]


def _payload(text: str) -> bytes | None:
    """A ``Program data:`` line's bytes (its base64 parts, joined)."""
    try:
        return b"".join(base64.b64decode(part, validate=True) for part in text.split())
    except (binascii.Error, ValueError):
        return None


def read_logs(logs: Iterable[str]) -> LogRecords:
    """Attribute each ``Program data:`` and instruction name to the program
    running when it was logged (the invoke stack the runtime logs)."""
    stack: list[str] = []
    data: list[tuple[str, bytes]] = []
    names: list[tuple[str, str]] = []
    truncated = False
    for line in logs:
        if _INVOKE in line and line.startswith("Program "):
            stack.append(line.split()[1])
        elif line.startswith("Program ") and (
            line.endswith(" success") or " failed: " in line
        ):
            if stack:
                stack.pop()
        elif LOG_TRUNCATED in line:
            truncated = True
        elif stack:
            _record(line, stack[-1], data, names)
    return LogRecords(tuple(data), tuple(names), truncated)


def _record(
    line: str,
    program: str,
    data: list[tuple[str, bytes]],
    names: list[tuple[str, str]],
) -> None:
    if line.startswith(_DATA):
        payload = _payload(line[len(_DATA) :])
        if payload is not None:
            data.append((program, payload))
    elif line.startswith(_LOG_INSTRUCTION):
        names.append((program, line[len(_LOG_INSTRUCTION) :].strip()))


# -- LaunchLab ------------------------------------------------------------------
TRADE_EVENT_SIZE = 147
TRADE_FIELDS = (
    "total_base_sell",
    "virtual_base",
    "virtual_quote",
    "real_base_before",
    "real_quote_before",
    "real_base_after",
    "real_quote_after",
    "amount_in",
    "amount_out",
    "protocol_fee",
    "platform_fee",
    "creator_fee",
    "share_fee",
)


@dataclass(frozen=True)
class TradeEvent:
    """LaunchLab's ``TradeEvent``: one curve trade, in raw units."""

    pool: str
    values: Mapping[str, int]
    side: str
    pool_status: str
    exact_in: bool

    def row_fields(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "side": self.side,
            "pool_status": self.pool_status,
            "exact_in": self.exact_in,
            **self.values,
        }


def decode_trade_event(raw: bytes) -> TradeEvent | None:
    if len(raw) != TRADE_EVENT_SIZE or raw[:8] != TRADE_EVENT:
        return None
    direction, status, exact_in = raw[144], raw[145], raw[146]
    if direction >= len(TRADE_DIRECTIONS) or status >= len(POOL_STATUSES):
        return None
    numbers = struct.unpack_from("<13Q", raw, 40)
    return TradeEvent(
        pool=pubkey_at(raw, 8),
        values=dict(zip(TRADE_FIELDS, numbers, strict=True)),
        side=TRADE_DIRECTIONS[direction],
        pool_status=POOL_STATUSES[status],
        exact_in=bool(exact_in),
    )


@dataclass(frozen=True)
class PoolCreateEvent:
    """LaunchLab's ``PoolCreateEvent`` (a constant-product curve's terms;
    ``curve`` is ``fixed`` or ``linear`` for the other two kinds)."""

    pool: str
    creator: str
    global_config: str
    decimals: int
    name: str
    symbol: str
    uri: str
    curve: str
    supply: int
    total_base_sell: int | None
    total_quote_fund_raising: int
    migrate_type: int
    vesting_locked: int
    vesting_cliff: int
    vesting_unlock: int

    @property
    def uri_host(self) -> str | None:
        try:
            return urlsplit(self.uri).hostname
        except ValueError:
            return None


CURVES = ("constant", "fixed", "linear")


def _string(raw: bytes, offset: int) -> tuple[str, int]:
    (length,) = struct.unpack_from("<I", raw, offset)
    end = offset + 4 + length
    if end > len(raw):
        raise ValueError("string past the end")
    return raw[offset + 4 : end].decode("utf-8", errors="replace"), end


def _curve(raw: bytes, offset: int) -> tuple[tuple[Any, ...], int]:
    kind = raw[offset]
    if kind >= len(CURVES):
        raise ValueError("unknown curve")
    if kind == 0:
        supply, total_sell, raising = struct.unpack_from("<3Q", raw, offset + 1)
        return (
            CURVES[kind],
            supply,
            total_sell,
            raising,
            raw[offset + 25],
        ), offset + 26
    supply, raising = struct.unpack_from("<2Q", raw, offset + 1)
    return (CURVES[kind], supply, None, raising, raw[offset + 17]), offset + 18


def decode_pool_create_event(raw: bytes) -> PoolCreateEvent | None:
    if raw[:8] != POOL_CREATE_EVENT:
        return None
    try:
        decimals = raw[104]
        name, offset = _string(raw, 105)
        symbol, offset = _string(raw, offset)
        uri, offset = _string(raw, offset)
        (curve, supply, total_sell, raising, migrate_type), offset = _curve(raw, offset)
        locked, cliff, unlock = struct.unpack_from("<3Q", raw, offset)
    except (IndexError, ValueError, struct.error):
        return None
    return PoolCreateEvent(
        pool=pubkey_at(raw, 8),
        creator=pubkey_at(raw, 40),
        global_config=pubkey_at(raw, 72),
        decimals=decimals,
        name=name,
        symbol=symbol,
        uri=uri,
        curve=curve,
        supply=supply,
        total_base_sell=total_sell,
        total_quote_fund_raising=raising,
        migrate_type=migrate_type,
        vesting_locked=locked,
        vesting_cliff=cliff,
        vesting_unlock=unlock,
    )


@dataclass(frozen=True)
class LaunchlabPool:
    """A LaunchLab pool account (429 bytes): its status, curve terms,
    reserves, platform, mints and vaults."""

    status: int
    base_decimals: int
    quote_decimals: int
    supply: int
    total_base_sell: int
    virtual_base: int
    virtual_quote: int
    real_base: int
    real_quote: int
    total_quote_fund_raising: int
    platform: str
    base_mint: str
    quote_mint: str
    base_vault: str
    quote_vault: str

    def terms(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "status": self.status,
            "base_decimals": self.base_decimals,
            "quote_decimals": self.quote_decimals,
            "supply": self.supply,
            "total_base_sell": self.total_base_sell,
            "virtual_base": self.virtual_base,
            "virtual_quote": self.virtual_quote,
            "real_base": self.real_base,
            "real_quote": self.real_quote,
            "total_quote_fund_raising": self.total_quote_fund_raising,
            "base_vault": self.base_vault,
            "quote_vault": self.quote_vault,
        }


def account_bytes(value: Mapping[str, Any] | None, owner: str) -> bytes | None:
    """The bytes of a base64 account read owned by ``owner``, else ``None``."""
    if not value or str(value.get("owner") or "") != owner:
        return None
    try:
        return base64.b64decode((value.get("data") or [""])[0], validate=True)
    except (binascii.Error, TypeError, ValueError):
        return None


def decode_launchlab_pool(value: Mapping[str, Any] | None) -> LaunchlabPool | None:
    raw = account_bytes(value, LAUNCHLAB_PROGRAM_ID)
    if raw is None or len(raw) != LAUNCHLAB_POOL_SIZE:
        return None
    supply, total_sell, virtual_base, virtual_quote, real_base, real_quote, raising = (
        struct.unpack_from("<7Q", raw, 21)
    )
    return LaunchlabPool(
        status=raw[17],
        base_decimals=raw[18],
        quote_decimals=raw[19],
        supply=supply,
        total_base_sell=total_sell,
        virtual_base=virtual_base,
        virtual_quote=virtual_quote,
        real_base=real_base,
        real_quote=real_quote,
        total_quote_fund_raising=raising,
        platform=pubkey_at(raw, 173),
        base_mint=pubkey_at(raw, 205),
        quote_mint=pubkey_at(raw, 237),
        base_vault=pubkey_at(raw, 269),
        quote_vault=pubkey_at(raw, 301),
    )


@dataclass(frozen=True)
class PlatformFees:
    """A LaunchLab platform config's fee rates, in basis points a side."""

    platform: str
    platform_fee_bps: float
    creator_fee_bps: float

    @property
    def total_fee_bps(self) -> float:
        protocol = PROTOCOL_FEE_RATE / FEE_RATE_DENOMINATOR * 10_000
        return protocol + self.platform_fee_bps + self.creator_fee_bps


def decode_platform_fees(
    address: str, value: Mapping[str, Any] | None
) -> PlatformFees | None:
    raw = account_bytes(value, LAUNCHLAB_PROGRAM_ID)
    if raw is None or len(raw) < 728:
        return None
    (platform_rate,) = struct.unpack_from("<Q", raw, 104)
    (creator_rate,) = struct.unpack_from("<Q", raw, 720)
    scale = 10_000 / FEE_RATE_DENOMINATOR
    return PlatformFees(address, platform_rate * scale, creator_rate * scale)


FLOAT_PLATFORM_COUNT_OFFSET = 106
FLOAT_MAX_PLATFORMS = 8


def decode_float_platforms(value: Mapping[str, Any] | None) -> tuple[str, ...] | None:
    """The platform configs Float's config account lists (a count at byte
    106, then the keys), ``None`` when the account does not read so."""
    raw = account_bytes(value, FLOAT_PROGRAM_ID)
    if raw is None or len(raw) <= FLOAT_PLATFORM_COUNT_OFFSET:
        return None
    count = raw[FLOAT_PLATFORM_COUNT_OFFSET]
    start = FLOAT_PLATFORM_COUNT_OFFSET + 1
    if not 1 <= count <= FLOAT_MAX_PLATFORMS or start + 32 * count > len(raw):
        return None
    return tuple(pubkey_at(raw, start + 32 * index) for index in range(count))


# -- Float -----------------------------------------------------------------------
@dataclass(frozen=True)
class FloatLaunch:
    """Float's launch event: the coin, its quote, the curve, who launched it."""

    mint: str
    quote_mint: str
    pool: str
    launcher: str
    second_key: str
    symbol: str | None


def decode_float_launch(raw: bytes) -> FloatLaunch | None:
    if raw[:8] != FLOAT_LAUNCH_EVENT or len(raw) < 168:
        return None
    symbol: str | None
    try:
        symbol, _ = _string(raw, 169)
    except (struct.error, ValueError):
        symbol = None
    return FloatLaunch(
        mint=pubkey_at(raw, 8),
        quote_mint=pubkey_at(raw, 40),
        pool=pubkey_at(raw, 72),
        launcher=pubkey_at(raw, 104),
        second_key=pubkey_at(raw, 136),
        symbol=symbol,
    )


# -- CPMM -------------------------------------------------------------------------
CPMM_SWAP_SIZE = 170


@dataclass(frozen=True)
class CpmmSwap:
    """CPMM's ``SwapEvent``, in raw units."""

    pool: str
    input_vault_before: int
    output_vault_before: int
    input_amount: int
    output_amount: int
    input_transfer_fee: int
    output_transfer_fee: int
    base_input: bool
    input_mint: str
    output_mint: str
    trade_fee: int
    creator_fee: int
    creator_fee_on_input: bool

    def row_fields(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "input_amount": self.input_amount,
            "output_amount": self.output_amount,
            "input_vault_before": self.input_vault_before,
            "output_vault_before": self.output_vault_before,
            "input_transfer_fee": self.input_transfer_fee,
            "output_transfer_fee": self.output_transfer_fee,
            "trade_fee": self.trade_fee,
            "creator_fee": self.creator_fee,
            "creator_fee_on_input": self.creator_fee_on_input,
            "base_input": self.base_input,
        }


def decode_cpmm_swap(raw: bytes) -> CpmmSwap | None:
    if len(raw) != CPMM_SWAP_SIZE or raw[:8] != CPMM_SWAP_EVENT:
        return None
    vault_in, vault_out, amount_in, amount_out, fee_in, fee_out = struct.unpack_from(
        "<6Q", raw, 40
    )
    trade_fee, creator_fee = struct.unpack_from("<2Q", raw, 153)
    return CpmmSwap(
        pool=pubkey_at(raw, 8),
        input_vault_before=vault_in,
        output_vault_before=vault_out,
        input_amount=amount_in,
        output_amount=amount_out,
        input_transfer_fee=fee_in,
        output_transfer_fee=fee_out,
        base_input=bool(raw[88]),
        input_mint=pubkey_at(raw, 89),
        output_mint=pubkey_at(raw, 121),
        trade_fee=trade_fee,
        creator_fee=creator_fee,
        creator_fee_on_input=bool(raw[169]),
    )


@dataclass(frozen=True)
class CpmmPool:
    """A CPMM pool account: its vaults and mints, and the fees held in the
    vaults that are not the pool's reserves (protocol, fund, creator)."""

    vault_0: str
    vault_1: str
    mint_0: str
    mint_1: str
    held_fees_0: int
    held_fees_1: int


def decode_cpmm_pool(value: Mapping[str, Any] | None) -> CpmmPool | None:
    raw = account_bytes(value, CPMM_PROGRAM_ID)
    if raw is None or len(raw) != CPMM_POOL_SIZE:
        return None
    protocol_0, protocol_1, fund_0, fund_1 = struct.unpack_from("<4Q", raw, 341)
    creator_0, creator_1 = struct.unpack_from("<2Q", raw, 397)
    return CpmmPool(
        vault_0=pubkey_at(raw, 72),
        vault_1=pubkey_at(raw, 104),
        mint_0=pubkey_at(raw, 168),
        mint_1=pubkey_at(raw, 200),
        held_fees_0=protocol_0 + fund_0 + creator_0,
        held_fees_1=protocol_1 + fund_1 + creator_1,
    )


# -- the migration ------------------------------------------------------------------
@dataclass(frozen=True)
class Migration:
    """``migrate_to_cpswap``'s accounts (LaunchLab's IDL order)."""

    signature: str
    slot: int | None
    block_time: int | None
    base_mint: str
    quote_mint: str
    platform: str
    cpmm_pool: str
    cpmm_base_vault: str
    cpmm_quote_vault: str
    pool: str


def _account_keys(tx: Mapping[str, Any]) -> list[str]:
    message = (tx.get("transaction") or {}).get("message") or {}
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    return [
        *map(str, message.get("accountKeys") or []),
        *map(str, loaded.get("writable") or []),
        *map(str, loaded.get("readonly") or []),
    ]


def _instructions(tx: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    message = (tx.get("transaction") or {}).get("message") or {}
    yield from message.get("instructions") or []
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        yield from inner.get("instructions") or []


def _migrate_accounts(tx: Mapping[str, Any], keys: Sequence[str]) -> list[str] | None:
    for instruction in _instructions(tx):
        index = int(instruction.get("programIdIndex", -1))
        if not 0 <= index < len(keys) or keys[index] != LAUNCHLAB_PROGRAM_ID:
            continue
        try:
            data = base58.b58decode(str(instruction.get("data") or ""))
        except ValueError:
            continue
        accounts = [keys[i] for i in instruction.get("accounts") or [] if i < len(keys)]
        if data[:8] == MIGRATE_TO_CPSWAP and len(accounts) >= 18:
            return accounts
    return None


def decode_migration(tx: Mapping[str, Any] | None) -> Migration | None:
    """The migration in a ``getTransaction`` answer (``json`` encoding),
    else ``None``."""
    if not tx:
        return None
    keys = _account_keys(tx)
    accounts = _migrate_accounts(tx, keys)
    if accounts is None:
        return None
    signatures = (tx.get("transaction") or {}).get("signatures") or [""]
    return Migration(
        signature=str(signatures[0]),
        slot=tx.get("slot"),
        block_time=tx.get("blockTime"),
        base_mint=accounts[1],
        quote_mint=accounts[2],
        platform=accounts[3],
        cpmm_pool=accounts[5],
        cpmm_base_vault=accounts[8],
        cpmm_quote_vault=accounts[9],
        pool=accounts[17],
    )


def transaction_signers(tx: Mapping[str, Any] | None) -> list[str]:
    """The signers of a ``getTransaction`` answer, the fee payer first."""
    if not tx:
        return []
    message = (tx.get("transaction") or {}).get("message") or {}
    header = message.get("header") or {}
    count = int(header.get("numRequiredSignatures") or 0)
    return [str(key) for key in (message.get("accountKeys") or [])[:count]]


__all__ = [
    "CPMM_PROGRAM_ID",
    "FEE_INSTRUCTIONS",
    "FLOAT_CONFIG",
    "FLOAT_LAUNCH_EVENT",
    "FLOAT_PLATFORMS",
    "FLOAT_PROGRAM_ID",
    "LAUNCHLAB_PROGRAM_ID",
    "LAUNCH_INSTRUCTIONS",
    "MIGRATE_INSTRUCTION",
    "CpmmPool",
    "CpmmSwap",
    "FloatLaunch",
    "LaunchlabPool",
    "LogRecords",
    "Migration",
    "PlatformFees",
    "PoolCreateEvent",
    "TradeEvent",
    "account_bytes",
    "decode_cpmm_pool",
    "decode_cpmm_swap",
    "decode_float_launch",
    "decode_float_platforms",
    "decode_launchlab_pool",
    "decode_migration",
    "decode_platform_fees",
    "decode_pool_create_event",
    "decode_trade_event",
    "read_logs",
    "transaction_signers",
]
