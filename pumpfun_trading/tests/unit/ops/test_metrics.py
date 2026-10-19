"""Tests for runtime counters and latency telemetry (`ops/metrics.py`)."""

from __future__ import annotations

import pytest

from pumpfun_trading.ops.metrics import (
    COUNTER_NAMES,
    metrics_snapshot,
    new_runtime_metrics,
    record_latency_ms,
    record_metric,
    restore_metrics,
)


def test_new_metrics_are_zeroed() -> None:
    metrics = new_runtime_metrics()
    assert all(metrics[name] == 0 for name in COUNTER_NAMES)
    assert metrics["latency_ms"] == {
        "samples": 0,
        "avg_ms": 0.0,
        "last_ms": 0.0,
        "max_ms": 0.0,
        "total_ms": 0.0,
    }


def test_record_metric_increments_and_creates_counters() -> None:
    metrics = new_runtime_metrics()
    record_metric(metrics, "buys")
    record_metric(metrics, "buys", 2)
    record_metric(metrics, "new_counter", 3)
    metrics["broken"] = "x"
    record_metric(metrics, "broken")
    assert metrics["buys"] == 3
    assert metrics["new_counter"] == 3
    assert metrics["broken"] == 1


@pytest.mark.parametrize("name", ["latency_ms", "last_latency_ms"])
def test_latency_names_add_a_sample(name: str) -> None:
    metrics = new_runtime_metrics()
    record_metric(metrics, name, 10)
    record_metric(metrics, name, 30)
    lat = metrics["latency_ms"]
    assert lat["samples"] == 2
    assert lat["total_ms"] == pytest.approx(40.0)
    assert lat["avg_ms"] == pytest.approx(20.0)
    assert lat["last_ms"] == pytest.approx(30.0)
    assert lat["max_ms"] == pytest.approx(30.0)


def test_latency_summary_is_rebuilt_when_missing() -> None:
    metrics: dict[str, object] = {"latency_ms": None}
    record_latency_ms(metrics, 5.0)
    assert metrics["latency_ms"] == {
        "samples": 1,
        "avg_ms": 5.0,
        "last_ms": 5.0,
        "max_ms": 5.0,
        "total_ms": 5.0,
    }


def test_snapshot_copies_latency_summary() -> None:
    metrics = new_runtime_metrics()
    snapshot = metrics_snapshot(metrics)
    snapshot["latency_ms"]["samples"] = 99
    snapshot["buys"] = 7
    assert metrics["latency_ms"]["samples"] == 0
    assert metrics["buys"] == 0
    assert metrics_snapshot({"buys": 1}) == {"buys": 1}


def test_restore_reads_known_counters_and_latency_only() -> None:
    metrics = new_runtime_metrics()
    restore_metrics(
        metrics,
        {
            "buys": 4.0,
            "sells": "bad",
            "unknown": 9,
            "latency_ms": {"samples": 2, "avg_ms": 1.5},
        },
    )
    assert metrics["buys"] == 4
    assert metrics["sells"] == 0
    assert "unknown" not in metrics
    assert metrics["latency_ms"] == {"samples": 2, "avg_ms": 1.5}

    restore_metrics(metrics, {"latency_ms": "bad"})
    assert metrics["latency_ms"] == {"samples": 2, "avg_ms": 1.5}
