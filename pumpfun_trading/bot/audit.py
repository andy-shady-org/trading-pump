from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from rich.console import Console
from rich.table import Table


def _as_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            pass
        for candidate in (text, text.replace("Z", "+00:00")):
            try:
                return datetime.fromisoformat(candidate).timestamp()
            except ValueError:
                continue
        try:
            return datetime.strptime(text, "%Y-%m-%d").timestamp()
        except ValueError:
            return None
    return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def _payload_for(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def load_audit_records(path: str | Path) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def filter_audit_records(
    records: Iterable[dict[str, Any]],
    *,
    record_type: str | None = None,
    state: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    mint: str | None = None,
    token_name: str | None = None,
    mint_name: str | None = None,
    reason: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    date_from_ts = _as_timestamp(date_from)
    date_to_ts = _as_timestamp(date_to)
    name_filter = mint_name if mint_name is not None else token_name

    for record in records:
        record_type_value = str(record.get("type") or "").strip().lower()
        if record_type and record_type_value != record_type.strip().lower():
            continue

        record_state = str(record.get("state") or "").strip().lower()
        payload = _payload_for(record)
        payload_state = (
            str(payload.get("state") or payload.get("previous_state") or "")
            .strip()
            .lower()
        )
        state_value = record_state or payload_state
        if state and state_value != state.strip().lower():
            continue

        timestamp = _as_timestamp(record.get("timestamp"))
        if date_from_ts is not None and (timestamp is None or timestamp < date_from_ts):
            continue
        if date_to_ts is not None and (timestamp is None or timestamp > date_to_ts):
            continue

        mint_value = str(payload.get("mint") or record.get("mint") or "").strip()
        if mint and _normalize_text(mint_value) != _normalize_text(mint):
            continue

        token_name_value = str(
            payload.get("mint_name")
            or payload.get("token_name")
            or payload.get("display_name")
            or payload.get("displayName")
            or record.get("mint_name")
            or record.get("token_name")
            or (payload.get("name") if str(record.get("type")) != "metric" else "")
            or (record.get("name") if str(record.get("type")) != "metric" else "")
            or ""
        ).strip()
        if name_filter and _normalize_text(token_name_value) != _normalize_text(
            name_filter
        ):
            continue

        reason_value = str(
            payload.get("reason") or payload.get("trade_reason") or ""
        ).strip()
        if reason and _normalize_text(reason_value) != _normalize_text(reason):
            continue

        status_value = (
            str(payload.get("status") or payload.get("outcome") or "").strip().lower()
        )
        if status and status_value != status.strip().lower():
            continue

        filtered.append(record)

    if limit is not None:
        return filtered[:limit]
    return filtered


def summarize_audit_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records_list = list(records)
    by_type = Counter()
    by_state = Counter()
    by_reason = Counter()
    by_status = Counter()

    for record in records_list:
        record_type = str(record.get("type") or "unknown")
        by_type[record_type] += 1

        record_state = str(
            record.get("state") or (_payload_for(record).get("state") or "unknown")
        )
        by_state[record_state] += 1

        payload = _payload_for(record)
        reason_value = payload.get("reason") or payload.get("trade_reason")
        if reason_value is not None:
            by_reason[str(reason_value)] += 1

        status_value = payload.get("status") or payload.get("outcome")
        if status_value is not None:
            by_status[str(status_value)] += 1

    return {
        "total_records": len(records_list),
        "by_type": dict(sorted(by_type.items())),
        "by_state": dict(sorted(by_state.items())),
        "by_reason": dict(sorted(by_reason.items())),
        "by_status": dict(sorted(by_status.items())),
    }


def _format_record_time(record: dict[str, Any]) -> str:
    timestamp = _as_timestamp(record.get("timestamp"))
    if timestamp is None:
        return "-"
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def render_audit_table(
    records: Iterable[dict[str, Any]], console: Console | None = None
) -> None:
    table = Table(title="Audit trail", show_lines=False, header_style="bold cyan")
    table.add_column("Time", style="dim")
    table.add_column("Type")
    table.add_column("State")
    table.add_column("Mint Name")
    table.add_column("Mint")
    table.add_column("Reason")
    table.add_column("Status")

    for record in records:
        payload = _payload_for(record)
        mint_name = str(
            payload.get("mint_name")
            or payload.get("token_name")
            or payload.get("display_name")
            or payload.get("displayName")
            or record.get("mint_name")
            or record.get("token_name")
            or (payload.get("name") if str(record.get("type")) != "metric" else "")
            or (record.get("name") if str(record.get("type")) != "metric" else "")
            or "-"
        )
        mint_address = str(payload.get("mint") or record.get("mint") or "-")
        table.add_row(
            _format_record_time(record),
            str(record.get("type") or "-"),
            str(
                record.get("state")
                or payload.get("state")
                or payload.get("previous_state")
                or "-"
            ),
            mint_name,
            mint_address,
            str(payload.get("reason") or payload.get("trade_reason") or "-"),
            str(payload.get("status") or payload.get("outcome") or "-"),
        )

    target = console or Console()
    target.print(table)


def export_audit_records(records: Iterable[dict[str, Any]], path: str | Path) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(list(records), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return str(destination)


__all__ = [
    "load_audit_records",
    "filter_audit_records",
    "summarize_audit_records",
    "render_audit_table",
    "export_audit_records",
]
