"""A token's name and symbol, read from its mint account.

Pump.fun creates every coin as a Token-2022 mint with the TokenMetadata
extension, so the name, symbol and metadata URI sit in the mint account
itself: one account read, no third-party API. Older SPL-token mints keep
theirs in a separate Metaplex account and are shown by address.

The name is for people only (the dashboard, alerts, the audit trail's
``instrument_name``): no lane, filter or fill reads it, and a failed or
missing read leaves it unset. It is whatever the coin's creator typed, so it
is cleaned of control characters and cut to a sensible length here, and
trading-core escapes it before display (its TC-8).
"""

from __future__ import annotations

import base64
import struct
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from trading_pump.sdk.execution_types import TOKEN_2022_PROGRAM_ID_STR

# Token-2022 mint layout: the 82-byte base mint, padding to the account-type
# byte at 165 (1 = mint), then type-length-value extensions.
ACCOUNT_TYPE_OFFSET = 165
ACCOUNT_TYPE_MINT = 1
EXTENSIONS_OFFSET = 166
TOKEN_METADATA_EXTENSION = 19
# TokenMetadata: update authority (32) and mint (32), then length-prefixed
# (u32) name, symbol and uri.
_METADATA_STRINGS_OFFSET = 64
NAME_LIMIT = 32
SYMBOL_LIMIT = 12


@dataclass(frozen=True)
class TokenName:
    """A coin's name and symbol as its creator set them, cleaned."""

    name: str
    symbol: str

    @property
    def label(self) -> str | None:
        """``Name (SYMBOL)``, or the one that is set; ``None`` when neither."""
        if self.name and self.symbol and self.symbol.casefold() != self.name.casefold():
            return f"{self.name} ({self.symbol})"
        return self.name or self.symbol or None


def clean(text: str, limit: int) -> str:
    """``text`` without control or format characters, spaces collapsed, cut
    to ``limit`` characters (``…`` when cut)."""
    kept = "".join(
        " " if char.isspace() else char
        for char in text
        if char.isspace() or unicodedata.category(char)[0] != "C"
    )
    single = " ".join(kept.split())
    return single if len(single) <= limit else f"{single[: limit - 1]}…"


def _extensions(raw: bytes) -> Iterator[tuple[int, bytes]]:
    offset = EXTENSIONS_OFFSET
    while offset + 4 <= len(raw):
        kind, length = struct.unpack_from("<HH", raw, offset)
        yield kind, raw[offset + 4 : offset + 4 + length]
        offset += 4 + length


def _strings(value: bytes, count: int) -> list[str]:
    found, offset = [], _METADATA_STRINGS_OFFSET
    for _ in range(count):
        (length,) = struct.unpack_from("<I", value, offset)
        found.append(value[offset + 4 : offset + 4 + length].decode("utf-8", "replace"))
        offset += 4 + length
    return found


def parse_token_name(raw: bytes) -> TokenName | None:
    """The name in a Token-2022 mint account's bytes, or ``None``."""
    if len(raw) <= ACCOUNT_TYPE_OFFSET or raw[ACCOUNT_TYPE_OFFSET] != ACCOUNT_TYPE_MINT:
        return None
    for kind, value in _extensions(raw):
        if kind == TOKEN_METADATA_EXTENSION:
            name, symbol = _strings(value, 2)
            found = TokenName(clean(name, NAME_LIMIT), clean(symbol, SYMBOL_LIMIT))
            return found if found.label else None
    return None


def decode_token_name(value: Mapping[str, Any] | None) -> TokenName | None:
    """The name in an RPC account read (``getMultipleAccounts``, base64), or
    ``None`` when absent, not a Token-2022 mint, or malformed."""
    if not value or str(value.get("owner") or "") != TOKEN_2022_PROGRAM_ID_STR:
        return None
    try:
        raw = base64.b64decode((value.get("data") or [""])[0])
        return parse_token_name(raw)
    except Exception:
        return None


__all__ = [
    "NAME_LIMIT",
    "SYMBOL_LIMIT",
    "TOKEN_METADATA_EXTENSION",
    "TokenName",
    "clean",
    "decode_token_name",
    "parse_token_name",
]
