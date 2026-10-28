"""Solana public identifiers, so redaction never masks a mint or a wallet.

trading-core masks long, digit-bearing URL path segments as likely keys
(``trading_core.ops.redact``). Mints and wallet addresses have that shape
but are public; pumpfun-trading's redactor knew that (BUG-102), the core's
learns it through :func:`register_public_identifier`. Importing
``trading_pump`` registers :func:`is_solana_pubkey`, so the recorders, the
RPC pool and the module all redact the same way inside the engine and out.
"""

from __future__ import annotations

from solders.pubkey import Pubkey


def is_solana_pubkey(segment: str) -> bool:
    """A base58 32-byte public key (mint, wallet, pool, program)."""
    if not 32 <= len(segment) <= 44:
        return False
    try:
        Pubkey.from_string(segment)
    except Exception:
        return False
    return True


__all__ = ["is_solana_pubkey"]
