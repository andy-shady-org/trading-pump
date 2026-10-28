"""Shared test constants: keys, mints, endpoints and curve reserves.

Every value is deterministic and offline. ``SAMPLE_PRIVATE_KEY`` decodes to
64 zero bytes; ``decode_keypair`` turns that into the all-zero-seed keypair,
so it is a valid signer that holds no funds anywhere.
"""

from __future__ import annotations

SAMPLE_PRIVATE_KEY = "1" * 64
"""Base58 private key used by every test bot and execution client."""

SAMPLE_RPC_URL = "https://api.mainnet-beta.solana.com"
"""RPC URL handed to clients. Never reached: ``tests/conftest.py`` blocks DNS."""

SAMPLE_MINT = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
"""A valid mint pubkey (not a real Pump.fun token)."""

SAMPLE_PUMP_MINT = "HeL2L24LpcuSo5Wrtu1ToEhy22BySBy71Eitk7Anpump"
"""A mint with the Pump.fun ``…pump`` vanity suffix."""

WSOL_MINT = "So11111111111111111111111111111111111111112"
"""Wrapped SOL mint; also handy as a second valid mint."""

LAMPORTS_PER_SOL = 1_000_000_000

INITIAL_VIRTUAL_SOL_RESERVES = 30_000_000_000
INITIAL_VIRTUAL_TOKEN_RESERVES = 1_073_000_000_000_000
INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000
TOKEN_TOTAL_SUPPLY = 1_000_000_000_000_000
"""Reserves of a freshly created Pump.fun bonding curve (6-decimal tokens)."""
