"""Global pytest fixtures and environment isolation."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Isolate tests from ambient persistence and audit environment variables."""
    isolated_status_path = str(tmp_path / "bot_status.json")
    isolated_audit_path = str(tmp_path / "audit_trail.jsonl")

    monkeypatch.setenv("PUMPFUN_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_BOT_STATUS_PATH", isolated_status_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG_PATH", isolated_audit_path)
    monkeypatch.setenv("PUMPFUN_AUDIT_LOG", isolated_audit_path)
