"""Run provenance: which build, config and fee schedule a run used (FEAT-68).

A paper or live result is only comparable with a replay, another run or a
release record when it says what produced it. :func:`collect_run_provenance`
gathers that at startup, without network access:

* the package version and, from the checkout the package runs from, the git
  commit, branch and whether tracked files were modified
  (``PUMPFUN_GIT_COMMIT`` names the commit for a deployment without ``.git``);
* a SHA-256 of the effective config (URLs redacted first) and of the config
  file's bytes, so ``sha256sum configs/canary.json`` can be checked against it;
* the Pump.fun fee tiers read from chain at startup (BUG-138) next to the fee
  that paper and replay model;
* the cost-relevant environment switches (Jito on / off and tip sizes), never
  a key, URL or other secret.

The bot writes the result to the status file (``run_provenance``), as a
``run_started`` audit record and as an ``event: "run_provenance"`` row at the
start of a ``--record-replay`` capture.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import os
import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from trading_pump.ops.redact import redact_text, redact_url

PROVENANCE_EVENT = "run_provenance"
PROVENANCE_RECORD_TYPE = "run_started"
PACKAGE_NAME = "pumpfun-trading"
GIT_COMMIT_ENV = "PUMPFUN_GIT_COMMIT"
# Cost switches that change paper and replay results; none of them is secret.
COST_ENV_KEYS = (
    "PUMPFUN_USE_JITO",
    "PUMPFUN_JITO_TIP_LAMPORTS",
    "PUMPFUN_JITO_ENTRY_TIP_LAMPORTS",
    "PUMPFUN_JITO_EXIT_TIP_LAMPORTS",
)
GIT_TIMEOUT_SECONDS = 2.0
_PACKAGE_DIR = Path(__file__).resolve().parents[1]


def package_version() -> str:
    """Installed version of ``pumpfun-trading``, ``unknown`` when not installed."""
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return "unknown"


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_info(path: str | Path | None = None) -> dict[str, Any]:
    """Commit, branch and dirty flag of the checkout at ``path`` (local only)."""
    cwd = Path(path) if path is not None else _PACKAGE_DIR
    commit = _git(["rev-parse", "HEAD"], cwd)
    if commit is None:
        override = os.getenv(GIT_COMMIT_ENV, "").strip()
        return {
            "git_commit": override or None,
            "git_branch": None,
            "git_dirty": None,
            "git_source": "env" if override else "unavailable",
        }
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    status = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    return {
        "git_commit": commit,
        "git_branch": branch if branch and branch != "HEAD" else None,
        "git_dirty": None if status is None else bool(status),
        "git_source": "checkout",
    }


def _redacted(value: Any) -> Any:
    if isinstance(value, str):
        return redact_url(value) if "://" in value else redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): _redacted(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redacted(v) for v in value]
    return value


def config_sha256(config: Any) -> str:
    """SHA-256 of a config's fields, URLs and secrets redacted first."""
    if dataclasses.is_dataclass(config) and not isinstance(config, type):
        data: Any = dataclasses.asdict(config)
    elif isinstance(config, Mapping):
        data = dict(config)
    else:
        raise TypeError(f"Cannot hash a {type(config).__name__} config")
    canonical = json.dumps(
        _redacted(data), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path | None) -> str | None:
    if not path:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def fee_tiers_summary(fee_config: Any) -> list[dict[str, Any]] | None:
    """The fee tiers of a decoded ``FeeConfig`` (BUG-138), ``None`` when unread."""
    tiers = getattr(fee_config, "fee_tiers", None)
    if not tiers:
        return None
    return [
        {
            "min_market_cap_sol": tier.market_cap_lamports_threshold / 1e9,
            "bonding_curve_bps": tier.fees.bonding_curve_bps,
            "protocol_fee_bps": tier.fees.protocol_fee_bps,
            "creator_fee_bps": tier.fees.creator_fee_bps,
            "lp_fee_bps": tier.fees.lp_fee_bps,
        }
        for tier in tiers
    ]


def cost_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if env is None else env
    return {key: source[key] for key in COST_ENV_KEYS if key in source}


def collect_run_provenance(
    config: Any,
    *,
    mode: str,
    config_path: str | Path | None = None,
    fee_config: Any = None,
    launch_fee_bps: int | None = None,
    modelled_fee_bps: int | None = None,
    started_at: float | None = None,
    git_path: str | Path | None = None,
) -> dict[str, Any]:
    """Everything needed to tell later which build and settings made a run."""
    ts = float(
        started_at
        if started_at is not None
        else _dt.datetime.now(_dt.timezone.utc).timestamp()
    )
    return {
        "started_at": ts,
        "started_at_utc": _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "package_version": package_version(),
        **git_info(git_path),
        "python_version": platform.python_version(),
        "platform": sys.platform,
        "pid": os.getpid(),
        "mode": mode,
        "strategy_preset": getattr(config, "strategy_preset", None),
        "entry_mode": getattr(config, "entry_mode", None),
        "config_path": str(config_path) if config_path else None,
        "config_file_sha256": file_sha256(config_path),
        "config_sha256": config_sha256(config),
        "fee_model_bps": modelled_fee_bps,
        "fee_launch_bps": launch_fee_bps,
        "fee_tiers": fee_tiers_summary(fee_config),
        "cost_env": cost_environment(),
    }


def provenance_capture_row(provenance: Mapping[str, Any]) -> dict[str, Any]:
    """The ``--record-replay`` row; replay and the shadow tools skip it."""
    return {
        "event": PROVENANCE_EVENT,
        "timestamp": provenance.get("started_at"),
        **{k: v for k, v in provenance.items() if k not in {"mint", "price"}},
    }


def short_build_label(provenance: Mapping[str, Any]) -> str:
    """``0.3.0rc4 @ 1a2b3c4d (dirty)`` for alerts and logs."""
    label = str(provenance.get("package_version") or "unknown")
    commit = provenance.get("git_commit")
    if commit:
        label += f" @ {str(commit)[:8]}"
        if provenance.get("git_dirty"):
            label += " (dirty)"
    return label


__all__ = [
    "COST_ENV_KEYS",
    "GIT_COMMIT_ENV",
    "PROVENANCE_EVENT",
    "PROVENANCE_RECORD_TYPE",
    "collect_run_provenance",
    "config_sha256",
    "cost_environment",
    "fee_tiers_summary",
    "file_sha256",
    "git_info",
    "package_version",
    "provenance_capture_row",
    "short_build_label",
]
