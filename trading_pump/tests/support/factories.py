"""Factories for the domain objects most tests need.

Built from the helpers that were copied between legacy files
(``make_bot`` / ``_make_bot``, four ``make_*pool_keys`` variants and about
150 inline ``TradingBotConfig(...)`` calls). Each factory takes keyword
overrides, so a test only states what matters to it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from solders.pubkey import Pubkey

from trading_pump.bot.position_manager import PositionManager
from trading_pump.bot.strategy import TradingBotConfig
from trading_pump.sdk.raydium import (
    RAYDIUM_AUTHORITY_V4,
    SERUM_PROGRAM_ID_V3,
    RaydiumPoolKeys,
)
from trading_pump.tests.support.constants import (
    SAMPLE_MINT,
    SAMPLE_PRIVATE_KEY,
    SAMPLE_RPC_URL,
    WSOL_MINT,
)

if TYPE_CHECKING:
    from trading_pump.bot.run import TradingBot

DEFAULT_CONFIG: dict[str, Any] = {"buy_amount_sol": 0.01, "dry_run": True}
"""Base for :func:`make_config`: the smallest trade size, never live."""


def make_config(**overrides: Any) -> TradingBotConfig:
    """Return a ``TradingBotConfig`` with test defaults plus ``overrides``.

    Defaults are ``buy_amount_sol=0.01`` and ``dry_run=True``; pass
    ``dry_run=False`` explicitly for a test of the live path.
    """
    return TradingBotConfig(**{**DEFAULT_CONFIG, **overrides})


def make_bot(
    tmp_path: Path | None = None,
    *,
    config: TradingBotConfig | None = None,
    private_key: str = SAMPLE_PRIVATE_KEY,
    rpc_url: str = SAMPLE_RPC_URL,
    verbose: bool = False,
    bot_kwargs: dict[str, Any] | None = None,
    **config_overrides: Any,
) -> TradingBot:
    """Return a ``TradingBot`` that never touches the network or the repo.

    With ``tmp_path`` the status snapshot and audit trail are written there
    (``status.json`` / ``audit.jsonl``); without it they fall back to the
    paths ``tests/conftest.py`` isolates. ``config_overrides`` go to
    :func:`make_config`; combining them with ``config`` is a ``TypeError``.
    Extra ``TradingBot`` keyword arguments go in ``bot_kwargs``.
    """
    from trading_pump.bot.run import TradingBot

    if config is None:
        config = make_config(**config_overrides)
    elif config_overrides:
        raise TypeError("pass either config= or config overrides, not both")
    kwargs: dict[str, Any] = {"verbose": verbose}
    if tmp_path is not None:
        kwargs["bot_status_path"] = str(tmp_path / "status.json")
        kwargs["audit_log_path"] = str(tmp_path / "audit.jsonl")
    kwargs.update(bot_kwargs or {})
    return TradingBot(
        private_key_b58=private_key,
        rpc_url=rpc_url,
        config=config,
        **kwargs,
    )


def make_position(
    target: TradingBot | PositionManager,
    mint: str = SAMPLE_MINT,
    *,
    token_amount: int = 350_000_000_000,
    cost_sol: float = 0.01,
    entry_market_cap: float = 30.0,
    **record_buy_kwargs: Any,
) -> dict[str, Any]:
    """Open a position through ``PositionManager.record_buy`` and return it.

    ``target`` is a bot (its ``position_manager`` is used) or a manager.
    Going through ``record_buy`` keeps the dict shape identical to live
    positions instead of hand-writing one.
    """
    manager = target if isinstance(target, PositionManager) else target.position_manager
    position: dict[str, Any] = manager.record_buy(
        mint,
        token_amount,
        cost_sol,
        entry_market_cap,
        **record_buy_kwargs,
    )
    return position


def make_pool_keys(
    mint: str = SAMPLE_MINT,
    *,
    pc_mint: str = WSOL_MINT,
    unique: bool = True,
    **overrides: str,
) -> RaydiumPoolKeys:
    """Return Raydium AMM v4 pool keys for ``mint`` / ``pc_mint``.

    With ``unique=True`` every account is a fresh valid pubkey, so tests that
    derive ATAs or build instructions work. ``unique=False`` uses the default
    pubkey everywhere, for tests that only round-trip the keys. Authority and
    Serum program ids are the real constants.
    """
    default = str(Pubkey.default())

    def account() -> str:
        return str(Pubkey.new_unique()) if unique else default

    fields: dict[str, str] = {
        name: account()
        for name in RaydiumPoolKeys.__slots__
        if name not in ("coin_mint", "pc_mint")
    }
    fields.update(
        amm_authority=RAYDIUM_AUTHORITY_V4,
        serum_program_id=SERUM_PROGRAM_ID_V3,
        coin_mint=mint,
        pc_mint=pc_mint,
    )
    fields.update(overrides)
    return RaydiumPoolKeys(**fields)
