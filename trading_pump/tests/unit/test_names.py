"""Unit tests for ``names.py``: a token's name from its Token-2022 mint."""

from __future__ import annotations

import base64
import struct

import pytest

from trading_pump.names import (
    NAME_LIMIT,
    TokenName,
    clean,
    decode_token_name,
    parse_token_name,
)
from trading_pump.sdk.execution_types import (
    TOKEN_2022_PROGRAM_ID_STR,
    TOKEN_PROGRAM_ID_STR,
)
from trading_pump.tests.support.payloads import GRADUATE_MINT_B64


def _string(text: bytes) -> bytes:
    return struct.pack("<I", len(text)) + text


def _mint_bytes(name: bytes, symbol: bytes, *, extra_before: bool = True) -> bytes:
    """A Token-2022 mint: base mint and padding, account type 1, a metadata
    pointer extension, then TokenMetadata."""
    metadata = bytes(64) + _string(name) + _string(symbol) + _string(b"https://u")
    pointer = struct.pack("<HH", 18, 64) + bytes(64)
    tokens = struct.pack("<HH", 19, len(metadata)) + metadata
    return bytes(165) + b"\x01" + (pointer if extra_before else b"") + tokens


def _read(raw: bytes, owner: str = TOKEN_2022_PROGRAM_ID_STR) -> dict:
    return {"owner": owner, "data": [base64.b64encode(raw).decode(), "base64"]}


def test_a_real_graduate_mint_carries_its_name() -> None:
    # 8ZZ8z349… read from mainnet on 2026-10-29 (tests/support/payloads.py).
    raw = base64.b64decode(GRADUATE_MINT_B64)
    found = parse_token_name(raw)
    assert found == TokenName("the future is bright", "bright")
    assert found.label == "the future is bright (bright)"
    assert decode_token_name(_read(raw)) == found


@pytest.mark.parametrize(
    ("name", "symbol", "label"),
    [
        ("Grok", "Grok", "Grok"),
        ("Fomo Family", "FOMO", "Fomo Family (FOMO)"),
        ("", "CAT", "CAT"),
        ("Cat", "", "Cat"),
    ],
)
def test_the_label_shows_the_symbol_only_when_it_adds_something(
    name: str, symbol: str, label: str
) -> None:
    assert TokenName(name, symbol).label == label


def test_names_are_cleaned_of_control_characters_and_cut() -> None:
    assert clean("a\x00b‮c\n\td  e", 32) == "abc d e"
    assert clean("x" * 40, NAME_LIMIT) == "x" * (NAME_LIMIT - 1) + "…"
    raw = _mint_bytes("🐱 crime\x07".encode(), b"\xff\xfeBAD", extra_before=False)
    assert parse_token_name(raw) == TokenName("🐱 crime", "��BAD")


def test_markup_is_kept_as_text_for_the_core_to_escape() -> None:
    raw = _mint_bytes(b"x [/] y", b"[red]")
    assert parse_token_name(raw) == TokenName("x [/] y", "[red]")


@pytest.mark.parametrize(
    "raw",
    [
        _mint_bytes(b"", b""),  # nothing to show
        bytes(165) + b"\x02" + _mint_bytes(b"A", b"A")[166:],  # not a mint
        bytes(82),  # a plain SPL mint: no extensions
        bytes(165) + b"\x01" + struct.pack("<HH", 18, 64) + bytes(64),  # no metadata
    ],
)
def test_no_name_when_there_is_none_to_read(raw: bytes) -> None:
    assert parse_token_name(raw) is None


def test_reads_that_are_not_token_2022_mints_or_are_broken_give_none() -> None:
    good = _mint_bytes(b"Cat", b"CAT")
    assert decode_token_name(None) is None
    assert decode_token_name(_read(good, owner=TOKEN_PROGRAM_ID_STR)) is None
    assert (
        decode_token_name({"owner": TOKEN_2022_PROGRAM_ID_STR, "data": ["!!"]}) is None
    )
    truncated = good[: len(good) - 20]  # the strings run past the end
    assert decode_token_name(_read(truncated)) is None
    assert decode_token_name({"owner": TOKEN_2022_PROGRAM_ID_STR}) is None
