"""``trading-pump land-probe``: the landing probe from this module (FEAT-175).

trading-solana's ``land_probe`` builds, sends and times the probes; it reads
no credentials and has no commands (its ADR-001), so this module runs it:

* the probe wallet's key comes from ``PUMPFUN_PROBE_PRIVATE_KEY`` only,
  never the trading key (a key equal to ``PUMPFUN_PRIVATE_KEY``'s is
  refused), and a wallet holding more than ``max_balance_sol`` is refused
  before anything is sent;
* the RPC and its WebSocket are ``PUMPFUN_RPC_URL`` and
  ``PUMPFUN_RPC_WS_URL`` (``config/env.py``); Jito's block engine and
  Helius Sender are chosen by region;
* each row is written to ``out`` (a new JSON Lines file) as it settles, so
  an interrupted run keeps what it measured; the report and, when asked,
  trading-core FEAT-176's delay sample are written at the end.

It sends nothing that trades and reads no capture, so it can run beside a
capture (the FEAT-175 run: 1 hour from home and 1 hour from the UK server,
at the same hours).
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_solana.jito import JITO_BLOCK_ENGINE_ENDPOINTS
from trading_solana.land_probe import (
    MODE_FAST,
    MODE_PRIORITY,
    MODES,
    LandProbe,
    ModeReport,
    ProbeRow,
    SpendCap,
    delay_sample_lines,
    make_plans,
    row_line,
    summarize,
)
from trading_solana.land_probe_io import RpcProbeIO, sender_url

from trading_pump.config.env import Credentials

LAMPORTS_PER_SOL = 1_000_000_000
DEFAULT_MAX_SPEND_SOL = 0.01
DEFAULT_MAX_TIP_LAMPORTS = 10_000
DEFAULT_TIP_LAMPORTS = 5_000
DEFAULT_MAX_BALANCE_SOL = 0.05


@dataclass(frozen=True)
class ProbeOptions:
    """What ``land-probe`` was asked to do."""

    modes: tuple[str, ...]
    count: int
    interval_seconds: float
    out: Path
    host: str
    cu_price_micro_lamports: int | None = None
    tip_lamports: int = DEFAULT_TIP_LAMPORTS
    max_tip_lamports: int = DEFAULT_MAX_TIP_LAMPORTS
    max_spend_sol: float = DEFAULT_MAX_SPEND_SOL
    max_balance_sol: float = DEFAULT_MAX_BALANCE_SOL
    jito_region: str = "frankfurt"
    sender_region: str = "lon"
    delays: Path | None = None

    def __post_init__(self) -> None:
        unknown = sorted(set(self.modes) - set(MODES))
        if not self.modes or unknown:
            raise ValueError(f"modes must be some of {', '.join(MODES)}")
        if self.count <= 0 or self.interval_seconds < 0:
            raise ValueError("count must be positive and interval not negative")
        if self.max_spend_sol <= 0 or self.max_balance_sol <= 0:
            raise ValueError("max-spend and max-balance must be positive")
        if self.jito_region not in JITO_BLOCK_ENGINE_ENDPOINTS:
            raise ValueError(
                f"unknown Jito region {self.jito_region!r}: one of "
                f"{', '.join(sorted(JITO_BLOCK_ENGINE_ENDPOINTS))}"
            )
        sender_url(self.sender_region)  # raises for an unknown region
        if self.out.exists():
            raise ValueError(f"{self.out} exists: give a new file")

    @property
    def max_spend_lamports(self) -> int:
        return int(round(self.max_spend_sol * LAMPORTS_PER_SOL))

    @property
    def priced(self) -> bool:
        return any(mode in (MODE_PRIORITY, MODE_FAST) for mode in self.modes)


@dataclass
class ProbeResult:
    rows: list[ProbeRow]
    reports: list[ModeReport]
    stopped_by_cap: bool
    cu_price_micro_lamports: int
    balance_lamports: int
    report_path: Path


IoFactory = Callable[..., Any]


def build_io(options: ProbeOptions, credentials: Credentials) -> RpcProbeIO:
    return RpcProbeIO(
        rpc_url=credentials.rpc_urls[0],
        ws_url=credentials.rpc_ws_connect_url(),
        jito_url=JITO_BLOCK_ENGINE_ENDPOINTS[options.jito_region],
        fast_url=sender_url(options.sender_region),
    )


async def _checked_balance(io: Any, address: str, options: ProbeOptions) -> int:
    balance = int(await io.balance(address))
    if balance > options.max_balance_sol * LAMPORTS_PER_SOL:
        raise ValueError(
            f"the probe wallet holds {balance / LAMPORTS_PER_SOL:.4f} SOL, more "
            f"than {options.max_balance_sol:g}: use a dedicated probe wallet"
        )
    return balance


async def _cu_price(io: Any, options: ProbeOptions) -> int:
    if not options.priced:
        return 0
    if options.cu_price_micro_lamports is not None:
        return int(options.cu_price_micro_lamports)
    return int(await io.recent_cu_price())


def report_path(out: Path) -> Path:
    return out.with_name(out.name + ".report.json")


def _write_report(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


async def run_land_probe(
    options: ProbeOptions,
    credentials: Credentials,
    *,
    io_factory: IoFactory = build_io,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], Any] = asyncio.sleep,
) -> ProbeResult:
    """Run the probe; see the module docstring. A refused wallet or an
    unreachable RPC raises before anything is sent."""
    keypair = credentials.probe_keypair()
    io = io_factory(options, credentials)
    await io.start()
    try:
        balance = await _checked_balance(io, str(keypair.pubkey()), options)
        price = await _cu_price(io, options)
        plans = make_plans(
            options.modes,
            cu_price_micro_lamports=price,
            tip_lamports=options.tip_lamports,
            max_tip_lamports=options.max_tip_lamports,
        )
        with options.out.open("x", encoding="utf-8") as handle:

            def write(row: ProbeRow) -> None:
                handle.write(row_line(row) + "\n")
                handle.flush()

            probe = LandProbe(
                io=io,
                keypair=keypair,
                plans=plans,
                host=options.host,
                cap=SpendCap(options.max_spend_lamports),
                clock=clock,
                sleep=sleep,
                on_row=write,
            )
            rows = await probe.run(options.count, options.interval_seconds)
    finally:
        await io.close()
    reports = summarize(rows)
    path = report_path(options.out)
    _write_report(
        path,
        {
            "host": options.host,
            "wallet": str(keypair.pubkey()),
            "balance_lamports": balance,
            "cu_price_micro_lamports": price,
            "tip_lamports": options.tip_lamports,
            "stopped_by_cap": probe.stopped_by_cap,
            "spend_reserved_lamports": probe.cap.reserved,
            "reports": [report.to_dict() for report in reports],
        },
    )
    if options.delays is not None:
        lines = delay_sample_lines(rows)
        options.delays.write_text("".join(f"{line}\n" for line in lines))
    return ProbeResult(rows, reports, probe.stopped_by_cap, price, balance, path)


def format_seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def format_slots(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def format_cost(value: float | None) -> str:
    return "-" if value is None else f"{math.ceil(value):,}"


def report_cells(report: ModeReport) -> Sequence[str]:
    return (
        report.host,
        report.mode,
        f"{report.landed}/{report.sent}",
        f"{report.landing_rate:.0%}",
        f"{format_slots(report.slots_median)} / {format_slots(report.slots_p90)}",
        f"{format_seconds(report.seconds_median)} / "
        f"{format_seconds(report.seconds_p90)}",
        format_seconds(report.confirmed_median),
        format_cost(report.cost_per_landed_lamports),
    )


__all__ = [
    "DEFAULT_MAX_BALANCE_SOL",
    "DEFAULT_MAX_SPEND_SOL",
    "DEFAULT_MAX_TIP_LAMPORTS",
    "DEFAULT_TIP_LAMPORTS",
    "ProbeOptions",
    "ProbeResult",
    "build_io",
    "report_cells",
    "report_path",
    "run_land_probe",
]
