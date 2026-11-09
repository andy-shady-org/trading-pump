"""Unit tests for ``probe.py``: the landing probe run from this module (FEAT-175)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import base58
import pytest
from solders.keypair import Keypair
from trading_solana.land_probe import Landing, ModeReport
from trading_solana.land_probe_io import RpcProbeIO

from trading_pump.config.env import Credentials
from trading_pump.probe import (
    ProbeOptions,
    build_io,
    format_cost,
    format_seconds,
    format_slots,
    report_cells,
    report_path,
    run_land_probe,
)

BLOCKHASH = "4sGjMW1sUnHzSxGspuhpqLDx6wiyjNtZAMdL4VZHirAn"


def _key(keypair: Keypair) -> str:
    return base58.b58encode(bytes(keypair)).decode()


def _options(tmp_path: Path, **kwargs: Any) -> ProbeOptions:
    values: dict[str, Any] = {
        "modes": ("rpc", "priority"),
        "count": 2,
        "interval_seconds": 0.0,
        "out": tmp_path / "probe.jsonl",
        "host": "home",
    }
    values.update(kwargs)
    return ProbeOptions(**values)


class FakeProbeIO:
    """The chain for the run: every probe lands half a second after it is sent."""

    def __init__(self, balance: int = 10_000_000, recent: int = 777) -> None:
        self.balance_answer = balance
        self.recent = recent
        self.started = False
        self.closed = False
        self.sent: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def balance(self, address: str) -> int:
        return self.balance_answer

    async def recent_cu_price(self, accounts: Any = ()) -> int:
        self.price_accounts = list(accounts)
        return self.recent

    async def latest_blockhash(self) -> tuple[str, int]:
        return BLOCKHASH, 100

    def current_slot(self) -> int:
        return 50

    async def watch(self, signature: str) -> None:
        return None

    async def send(self, mode: str, raw: bytes, signature: str) -> None:
        self.sent.append(mode)

    async def wait_landed(self, signature: str, height: int, sent_at: float) -> Landing:
        return Landing(processed_at=sent_at + 0.5, confirmed_at=sent_at + 1.0, slot=52)

    async def fee(self, signature: str) -> tuple[int, int]:
        return 5_000, 52


def _credentials(probe: Keypair | None = None, trading: Keypair | None = None):
    return Credentials(
        private_key=_key(trading) if trading else None,
        probe_private_key=_key(probe) if probe else None,
        rpc_urls=("https://rpc.example/?api-key=x",),
    )


async def _no_sleep(seconds: float) -> None:
    return None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"modes": ()}, "modes must be some of"),
        ({"modes": ("rpc", "smoke")}, "modes must be some of"),
        ({"count": 0}, "count must be positive"),
        ({"interval_seconds": -1.0}, "interval not negative"),
        ({"max_spend_sol": 0.0}, "must be positive"),
        ({"max_balance_sol": 0.0}, "must be positive"),
        ({"jito_region": "moon"}, "unknown Jito region 'moon'"),
        ({"sender_region": "moon"}, "unknown Sender region"),
    ],
)
def test_options_refuse_what_cannot_run(tmp_path: Path, kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        _options(tmp_path, **kwargs)


def test_options_refuse_an_existing_rows_file(tmp_path: Path) -> None:
    (tmp_path / "probe.jsonl").write_text("")
    with pytest.raises(ValueError, match="exists: give a new file"):
        _options(tmp_path)


def test_options_say_what_they_cost_and_whether_they_need_a_price(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path, max_spend_sol=0.01)
    assert options.max_spend_lamports == 10_000_000 and options.priced
    assert not _options(tmp_path, modes=("rpc", "jito")).priced
    assert _options(tmp_path, modes=("fast",)).priced


def test_build_io_uses_the_region_endpoints(tmp_path: Path) -> None:
    io = build_io(_options(tmp_path), _credentials())
    assert isinstance(io, RpcProbeIO)
    assert io.rpc_url == "https://rpc.example/?api-key=x"
    assert io.ws_url == "wss://rpc.example/?api-key=x"
    assert io.jito_url == "https://frankfurt.mainnet.block-engine.jito.wtf"
    assert io.fast_url == "http://lon-sender.helius-rpc.com/fast?swqos_only=true"


async def test_the_run_writes_rows_report_and_delay_sample(tmp_path: Path) -> None:
    fake = FakeProbeIO()
    delays = tmp_path / "delays.txt"
    options = _options(tmp_path, delays=delays)
    ticks = iter(float(n) for n in range(100))
    result = await run_land_probe(
        options,
        _credentials(Keypair(), Keypair()),
        io_factory=lambda o, c: fake,
        clock=lambda: next(ticks),
        sleep=_no_sleep,
    )
    assert fake.started and fake.closed
    assert fake.sent == ["rpc", "priority", "rpc", "priority"]
    assert result.cu_price_micro_lamports == 777 and not result.stopped_by_cap
    assert len(fake.price_accounts) == 8  # Jito's tip accounts
    rows = [json.loads(line) for line in options.out.read_text().splitlines()]
    assert len(rows) == 4 and all(row["landed"] for row in rows)
    assert {row["cu_price_micro_lamports"] for row in rows} == {0, 777}
    report = json.loads(result.report_path.read_text())
    assert result.report_path == report_path(options.out)
    assert report["host"] == "home" and report["balance_lamports"] == 10_000_000
    assert [r["mode"] for r in report["reports"]] == ["rpc", "priority"]
    assert (
        delays.read_text().splitlines()
        == [
            "0.5000 land-probe:home:rpc",
            "0.5000 land-probe:home:priority",
        ]
        * 2
    )


async def test_a_given_price_is_used_and_unpriced_modes_need_none(
    tmp_path: Path,
) -> None:
    given = await run_land_probe(
        _options(tmp_path, cu_price_micro_lamports=5, out=tmp_path / "a.jsonl"),
        _credentials(Keypair()),
        io_factory=lambda o, c: FakeProbeIO(),
        sleep=_no_sleep,
    )
    assert given.cu_price_micro_lamports == 5
    unpriced = await run_land_probe(
        _options(
            tmp_path, modes=("jito",), out=tmp_path / "b.jsonl", max_spend_sol=1.0
        ),
        _credentials(Keypair()),
        io_factory=lambda o, c: FakeProbeIO(),
        sleep=_no_sleep,
    )
    assert unpriced.cu_price_micro_lamports == 0


async def test_a_wallet_holding_too_much_is_refused_before_any_send(
    tmp_path: Path,
) -> None:
    fake = FakeProbeIO(balance=60_000_000)
    options = _options(tmp_path)
    with pytest.raises(ValueError, match="holds 0.0600 SOL, more than 0.05"):
        await run_land_probe(
            options, _credentials(Keypair()), io_factory=lambda o, c: fake
        )
    assert fake.sent == [] and fake.closed and not options.out.exists()


async def test_no_probe_key_or_the_trading_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PUMPFUN_PROBE_PRIVATE_KEY is not set"):
        await run_land_probe(_options(tmp_path), _credentials())
    same = Keypair()
    with pytest.raises(ValueError, match="is the trading wallet's key"):
        await run_land_probe(_options(tmp_path), _credentials(same, same))


def test_the_report_cells_format_each_figure() -> None:
    report = ModeReport(
        host="uk",
        mode="jito",
        sent=10,
        landed=9,
        expired=1,
        landing_rate=0.9,
        slots_median=1.0,
        slots_p90=3.0,
        seconds_median=0.4123,
        seconds_p90=1.2,
        confirmed_median=0.9,
        cost_per_landed_lamports=6000.4,
    )
    assert report_cells(report) == (
        "uk",
        "jito",
        "9/10",
        "90%",
        "1 / 3",
        "0.412 / 1.200",
        "0.900",
        "6,001",
    )
    assert format_seconds(None) == format_slots(None) == format_cost(None) == "-"
