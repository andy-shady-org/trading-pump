"""Byte builders for Pump.fun account and event payloads.

The bonding-curve layout mirrors ``PumpFunCurveMixin.decode_bonding_curve_data``
(``sdk/pumpfun_execution.py``); the round-trip tests in
``tests/unit/test_support.py`` fail if either side drifts.
Pubkeys must be valid base58, so a payload never carries padded garbage.
"""

from __future__ import annotations

import base64
import struct

from solders.pubkey import Pubkey

from trading_pump.tests.support.constants import (
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    TOKEN_TOTAL_SUPPLY,
    WSOL_MINT,
)

BONDING_CURVE_DISCRIMINATOR = bytes([23, 108, 143, 219, 112, 126, 121, 100])
"""Anchor account discriminator of ``BondingCurve``."""

SAMPLE_USER = str(Pubkey.default())
SAMPLE_CURVE = WSOL_MINT
SAMPLE_TIMESTAMP = 1_728_600_000


NON_STANDARD_CURVE_RESERVES: tuple[tuple[int, int], ...] = (
    (8_233_357_569_630, 10),  # CEb8KGYB...pump, decoded to 7,673 SOL market cap
    (105_860_003_350_032, 0),  # 8CucYF88..., decoded to 98,658 SOL market cap
)
"""``(virtual_sol, real_sol)`` lamports of mainnet curves that broke paper
pricing in the v0.2.0 Stage 0 pilot (BUG-104); both had the standard
``virtual_token_reserves`` of 1.073e15 and ``real_token_reserves`` of 7.931e14."""

STANDARD_CURVE_RESERVES: tuple[tuple[int, int], ...] = (
    (30_001_716_240, 1_716_240),  # 4vfQCJJ1..., traded once
    (30_000_016_102, 16_102),  # bbrxy2Ke...
)
"""``(virtual_sol, real_sol)`` lamports of standard mainnet curves (same pilot)."""


def _pubkey_bytes(value: str) -> bytes:
    return bytes(Pubkey.from_string(value))


def bonding_curve_bytes(
    *,
    virtual_token_reserves: int = INITIAL_VIRTUAL_TOKEN_RESERVES,
    virtual_sol_reserves: int = INITIAL_VIRTUAL_SOL_RESERVES,
    real_token_reserves: int = INITIAL_REAL_TOKEN_RESERVES,
    real_sol_reserves: int = 0,
    token_total_supply: int = TOKEN_TOTAL_SUPPLY,
    complete: bool = False,
    creator: str | None = None,
) -> bytes:
    """Return a ``BondingCurve`` account buffer (fresh curve by default).

    Bytes 0..8 discriminator, five little-endian u64 reserves, the
    ``complete`` bool at 48, and with ``creator`` the creator pubkey at
    49..81 (where ``sdk/execution.py`` reads it).
    """
    data = BONDING_CURVE_DISCRIMINATOR + struct.pack(
        "<QQQQQ?",
        virtual_token_reserves,
        virtual_sol_reserves,
        real_token_reserves,
        real_sol_reserves,
        token_total_supply,
        complete,
    )
    if creator is not None:
        data += _pubkey_bytes(creator)
    return data


def account_data_b64(raw: bytes) -> list[str]:
    """Return ``[base64, "base64"]``, the RPC ``getAccountInfo`` data field."""
    return [base64.b64encode(raw).decode("ascii"), "base64"]


GRADUATED_MINT = "DJGsptd7CEMEKrHdmVPastxKcPNSqGJT5K7HWcn5pump"
GRADUATED_POOL = "B9WYSKaLDWnegupPNG1h99XiiokMUYj6k64Dbqv18qr8"
GRADUATED_CURVE_ADDRESS = "3gssU4VTiBwWWsovxhhgGNjBqY7gMbjdUkhwpdEJsmVM"
GRADUATED_CURVE_OWNER = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
GRADUATED_CURVE_B64 = (
    "F7f4N2DYrGAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAxqR+jQMAAZReNxJJhUQd"
    "aBTpxJgp1jAS2hdIlKMoRGQ7jKfTbt72AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)
GRADUATED_POOL_ADDRESS = "B9WYSKaLDWnegupPNG1h99XiiokMUYj6k64Dbqv18qr8"
GRADUATED_POOL_OWNER = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
GRADUATED_POOL_B64 = (
    "8ZptBBGxbbz+AAAYvzUvHEBS4PBAp7d9MLa5XqNsKSduYcM9GbZtR87IgLa5EXneKqTD3hNO9J6H"
    "MnYGVHeYOWKN4uAbXNiAp2NvBpuIV/6rgYT7aH9jRhjANdrEOdwa6ztVmKDwAAAAAAHNme0274Sg"
    "T9LaxlBZ9BLC+BZRuWG7pscA8RGieDTKIgrI2y45hOYMxtx9sbZiVHxqMm7NJqrRwG4F5H3aGjJW"
    "pAQC5mkm/y8JuBPO9GhsDjXP3h0wvxdOr/vWOtZjDmOAQ2tZ0AMAAJReNxJJhUQdaBTpxJgp1jAS"
    "2hdIlKMoRGQ7jKfTbt72AADJQR4YBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAA=="
)
GRADUATED_GLOBAL_CONFIG_ADDRESS = "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw"
GRADUATED_GLOBAL_CONFIG_OWNER = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
GRADUATED_GLOBAL_CONFIG_B64 = (
    "lQicyqD8sNnTu4yrNBzgUoRX8sOBfTJ4RBlj3NVf7Vi6JMmZ3awCqhQAAAAAAAAABQAAAAAAAAAA"
    "SsL40N1cvJfjKJwZfLUGKlTz2Va5zm5RFfllZ6pcs+ZgjMwd/OlhtDt3nBkVBabi079F1aTbRhit"
    "dsgtYXVFNWODcwAOoiyyZNNK/2SgS176v7t03c0EiZexmBVH19EQg4R0KS5nWpS0NuywqZiJQjKK"
    "g93GIzgClhJnxc1hF8uNGBoMhJ+pN6bzSt7TCB75VwCqywybs9kJpLkUdSek69eqj7Bg2CkbTE1H"
    "Xa/3Yslr3A2s6zbAEurRLtOpSEFh4ATIfOuY+lzkf4A4Bv0seUXSlSSVmuwA3tl4FPOPeEb/g4OB"
    "i6j6KMPNO21ek/n6uPCXm8NyFazFskaHe6jDyQUAAAAAAAAAByFdmUB5NpThFgZs5Fm4GP35u6DH"
    "tBt4P6OhIMpBlTKii1/SarR5pqnMbL9rCyPrYYhaNx4BIKypE77vPROKeOiTFB+xjp8VdNgQ4Xjh"
    "njBgTjF1qi5KMt/IYAcn0QcJATWEU2JWCU+RKBkSfvpORGtDM3IXk9E4dvmq2/PcfQtfbnUBgiD5"
    "QmdwAyN7TWtFN1m0pcaQtZw12bsYegkMvSozmHqeuxNnmatZklsT5dyLMIHfAF20J8FHj6Rv+MNH"
    "oHTpVD8+N6LQRiJ63ctOnHdMRCWMQ+3ySqiq4fACFGZb2kw4zW23Q49ZtAi7nsO0yp6K0fHyRlPE"
    "mbV5bCDb+bMt3Z7qPzmzchFccYR8GEXPpTbGhQdOAw5E0CHePvnjXEy3gPCO4v7oS+xEald4Jdpo"
    "1Dn6il2jsMXP9Q9j9FRrAUOeZRDAPWX62THonQS+C7cNUZcfUcQV+zRMB9tBnyEiAiNVFqkXE0xn"
    "WIxJOCCuFV7pZmVXesG3GNpH3c8qBQ7mp+IgaLuIZAqlf5CTCMYf73EaAWP1p1XAcLyGDR9jZyB8"
    "7NpbzGyx6vDxbWhARWaxjVbSSBrLMXAyZW6QVRx4RJZB+ElY3HOnaoXYdW9VwCzayom6GTJ5DDaK"
    "sVfpLXPFS5a1yTGUHkbqS+Lg4xEndE/Gt0z7RV7+r4vVcXks7UT8H3j5SjPQkJxea1+wIVcK2Nut"
    "jej9s9IO0c2Z645Oh3AVfuvrZ4plXbmbN/axMmx2V9uQz7ioer74x7byyGmIEwAAAAAAAPSEYofB"
    "0vyr1vGBX2l/VABW/RZVaGEbANPK6XSCwSxlAQEsAQAAAAAAAA=="
)
GRADUATED_BASE_VAULT_ADDRESS = "j6iUvMo6Z2yivpHmsME2nXrafjbhtbCJqdevsJstunV"
GRADUATED_BASE_VAULT_OWNER = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
GRADUATED_BASE_VAULT_B64 = (
    "trkRed4qpMPeE070nocydgZUd5g5Yo3i4Btc2ICnY2+WwutDHabNP/Av8usCrx9bqh1ZXijsfoH4"
    "PxmYLaT6GcAQO0vgrwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgcAAAA="
)
GRADUATED_QUOTE_VAULT_ADDRESS = "C3FQnUxE56fXfbTZTFLvddizyrQqXJsG7VRTvdSPk3uU"
GRADUATED_QUOTE_VAULT_OWNER = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
GRADUATED_QUOTE_VAULT_B64 = (
    "BpuIV/6rgYT7aH9jRhjANdrEOdwa6ztVmKDwAAAAAAGWwutDHabNP/Av8usCrx9bqh1ZXijsfoH4"
    "PxmYLaT6GUwF6CgRAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQEAAAA4"
    "thYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)


# Token-2022 mint 8ZZ8z349rrZG8VoJBBRpmgV5HFw2reESviaSoLoDpump
# (a 2026-10-29 graduate), read from
# mainnet: 386 bytes, decimals 6, supply 962,395,591,892,651 raw after burns (BUG-162).
GRADUATE_MINT = "8ZZ8z349rrZG8VoJBBRpmgV5HFw2reESviaSoLoDpump"
GRADUATE_MINT_SUPPLY = 962395591892651
GRADUATE_MINT_B64 = (
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAq15jL0trAwAGAQAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAARIAQAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHBYu4bEO423shWw1Q0Yeaqa8pPtC/sxo7La"
    "qRPPGEsPEwCUAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAcFi7hsQ7jbeyFbDVDRh5"
    "qpryk+0L+zGjstqpE88YSw8UAAAAdGhlIGZ1dHVyZSBpcyBicmlnaHQGAAAAYnJpZ2h0KgAAAGh0"
    "dHBzOi8vbWQuc2RmZ3NkZnNkZi51ay9tZXRhZGF0YS9MbW80YmZ3NwAAAAA="
)
