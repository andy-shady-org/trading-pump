"""Tests for run provenance (`ops/provenance.py`, FEAT-68)."""

from __future__ import annotations

import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest

from trading_pump.ops import provenance
from trading_pump.ops.provenance import (
    GIT_COMMIT_ENV,
    PROVENANCE_EVENT,
    collect_run_provenance,
    config_sha256,
    cost_environment,
    fee_tiers_summary,
    file_sha256,
    git_info,
    package_version,
    provenance_capture_row,
    short_build_label,
)
from trading_pump.sdk.fee_config import FeeConfig, FeeTier, Fees
from trading_pump.tests.support.factories import make_config


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], returncode, stdout=stdout, stderr="")


def test_git_info_reads_commit_branch_and_dirty_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answers = {
        "rev-parse HEAD": "a" * 40,
        "rev-parse --abbrev-ref HEAD": "rc4/implementation",
        "status --porcelain --untracked-files=no": " M bot/run.py",
    }
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(cmd)
        assert kwargs["timeout"] == provenance.GIT_TIMEOUT_SECONDS
        return _completed(answers[" ".join(cmd[1:])] + "\n")

    monkeypatch.setattr(provenance.subprocess, "run", fake_run)
    info = git_info("/somewhere")

    assert info == {
        "git_commit": "a" * 40,
        "git_branch": "rc4/implementation",
        "git_dirty": True,
        "git_source": "checkout",
    }
    assert all(cmd[0] == "git" for cmd in calls)


def test_git_info_detached_head_and_failed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess:
        if cmd[1] == "status":
            return _completed(returncode=128)
        return _completed("HEAD" if "--abbrev-ref" in cmd else "b" * 40)

    monkeypatch.setattr(provenance.subprocess, "run", fake_run)
    info = git_info()
    assert info["git_branch"] is None
    assert info["git_dirty"] is None


def test_git_info_without_a_checkout_uses_the_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_git(*_: Any, **__: Any) -> subprocess.CompletedProcess:
        raise FileNotFoundError("git")

    monkeypatch.setattr(provenance.subprocess, "run", no_git)
    assert git_info()["git_source"] == "unavailable"
    assert git_info()["git_commit"] is None

    monkeypatch.setenv(GIT_COMMIT_ENV, "deadbeef")
    info = git_info()
    assert info["git_commit"] == "deadbeef"
    assert info["git_source"] == "env"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_info_on_a_real_checkout(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q", "-b", "main")
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    git("add", "f.txt")
    git("commit", "-q", "-m", "c")
    clean = git_info(tmp_path)
    assert clean["git_branch"] == "main"
    assert clean["git_dirty"] is False
    assert len(clean["git_commit"]) == 40

    (tmp_path / "f.txt").write_text("2", encoding="utf-8")
    assert git_info(tmp_path)["git_dirty"] is True
    assert git_info(tmp_path / "missing")["git_source"] in {"unavailable", "env"}


def test_package_version_falls_back_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert package_version() != ""

    def missing(name: str) -> str:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(provenance.metadata, "version", missing)
    assert package_version() == "unknown"


def test_config_hash_is_stable_and_ignores_url_secrets() -> None:
    base = make_config(stream_url="wss://pumpportal.fun/api/data?api-key=SECRET1")
    other_key = make_config(stream_url="wss://pumpportal.fun/api/data?api-key=SECRET2")
    changed = make_config(
        stream_url="wss://pumpportal.fun/api/data?api-key=SECRET1", stop_loss=0.5
    )

    assert config_sha256(base) == config_sha256(base)
    assert config_sha256(base) == config_sha256(other_key)
    assert config_sha256(base) != config_sha256(changed)
    assert config_sha256({"a": [1, {"b": "x"}]}) == config_sha256(
        {"a": (1, {"b": "x"})}
    )
    with pytest.raises(TypeError):
        config_sha256(42)


def test_file_hash_fee_tiers_and_cost_environment(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    path.write_bytes(b"{}")
    assert file_sha256(path) == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert file_sha256(None) is None
    assert file_sha256(tmp_path / "missing.json") is None

    fee = FeeConfig(
        bump=1,
        admin="admin",
        flat_fees=Fees(0, 0, 0),
        fee_tiers=(
            FeeTier(0, Fees(0, 95, 30)),
            FeeTier(420_000_000_000, Fees(2, 93, 5)),
        ),
        stable_fee_tiers=(),
    )
    tiers = fee_tiers_summary(fee)
    assert tiers is not None
    assert tiers[1] == {
        "min_market_cap_sol": 420.0,
        "bonding_curve_bps": 98,
        "protocol_fee_bps": 93,
        "creator_fee_bps": 5,
        "lp_fee_bps": 2,
    }
    assert fee_tiers_summary(None) is None

    env = {
        "PUMPFUN_USE_JITO": "true",
        "PUMPFUN_JITO_TIP_LAMPORTS": "25000",
        "PUMPFUN_PRIVATE_KEY": "never",
        "PUMPFUN_STREAM_API_KEY": "never",
    }
    assert cost_environment(env) == {
        "PUMPFUN_USE_JITO": "true",
        "PUMPFUN_JITO_TIP_LAMPORTS": "25000",
    }


def test_collect_run_provenance_and_capture_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        provenance,
        "git_info",
        lambda path=None: {
            "git_commit": "c0ffee" * 6 + "abcd",
            "git_branch": "main",
            "git_dirty": True,
            "git_source": "checkout",
        },
    )
    monkeypatch.setenv("PUMPFUN_JITO_TIP_LAMPORTS", "25000")
    config_file = tmp_path / "canary.json"
    config_file.write_text('{"buy_amount_sol": 0.02}', encoding="utf-8")
    config = make_config(strategy_preset="momentum")

    stamp = collect_run_provenance(
        config,
        mode="paper",
        config_path=config_file,
        launch_fee_bps=125,
        modelled_fee_bps=125,
        started_at=1_792_022_400.0,
    )

    assert stamp["started_at_utc"] == "2026-10-15T00:00:00Z"
    assert stamp["mode"] == "paper"
    assert stamp["strategy_preset"] == "momentum"
    assert stamp["config_sha256"] == config_sha256(config)
    assert stamp["config_file_sha256"] == file_sha256(config_file)
    assert stamp["config_path"] == str(config_file)
    assert stamp["fee_model_bps"] == 125 and stamp["fee_launch_bps"] == 125
    assert stamp["fee_tiers"] is None
    assert stamp["cost_env"] == {"PUMPFUN_JITO_TIP_LAMPORTS": "25000"}
    assert short_build_label(stamp).endswith("@ c0ffeec0 (dirty)")

    row = provenance_capture_row({**stamp, "mint": "x", "price": 1.0})
    assert row["event"] == PROVENANCE_EVENT
    assert row["timestamp"] == 1_792_022_400.0
    assert "mint" not in row and "price" not in row

    now = collect_run_provenance(make_config(), mode="live", git_path=tmp_path)
    assert now["config_path"] is None and now["config_file_sha256"] is None
    assert now["started_at"] > 1_792_022_400.0


def test_short_build_label_without_a_commit() -> None:
    assert short_build_label({"package_version": "0.3.0rc4"}) == "0.3.0rc4"
    assert short_build_label({}) == "unknown"
    assert (
        short_build_label({"package_version": "1", "git_commit": "1234567890"})
        == "1 @ 12345678"
    )
