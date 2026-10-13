from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional, TextIO

logger = logging.getLogger(__name__)


class StatusPersistenceManager:
    """Handles snapshot persistence (bot_status.json), crash recovery, and append-only audit logging."""

    def __init__(
        self,
        bot_status_path: Optional[str] = None,
        audit_log_path: Optional[str] = None,
    ) -> None:
        self.bot_status_path = bot_status_path
        self.audit_log_path = audit_log_path
        self._audit_handle: Optional[TextIO] = None

        if self.audit_log_path:
            try:
                parent_dir = os.path.dirname(self.audit_log_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                self._audit_handle = open(self.audit_log_path, "a", encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "Unable to open audit log file at %s: %s",
                    self.audit_log_path,
                    exc,
                )

    def write_status_snapshot(self, snapshot: dict[str, Any]) -> bool:
        """Atomically serializes runtime state to bot_status.json."""
        if not self.bot_status_path:
            return False

        parent_dir = os.path.dirname(self.bot_status_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        try:
            # Atomic write via temp file rename
            temp_path = f"{self.bot_status_path}.tmp.{os.getpid()}"
            with open(temp_path, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.bot_status_path)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to write bot status snapshot to %s: %s",
                self.bot_status_path,
                exc,
            )
            return False

    def load_status_snapshot(self) -> Optional[dict[str, Any]]:
        """Safely loads persisted snapshot from bot_status.json for crash recovery."""
        if not self.bot_status_path or not os.path.exists(self.bot_status_path):
            return None

        try:
            with open(self.bot_status_path, "r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
            if isinstance(snapshot, dict):
                return snapshot
            logger.warning(
                "Persisted status at %s has non-dict structure", self.bot_status_path
            )
            return None
        except Exception as exc:
            logger.warning(
                "Could not read persisted status file at %s: %s",
                self.bot_status_path,
                exc,
            )
            return None

    def write_audit_record(
        self,
        record_type: str,
        state: str,
        payload: dict[str, Any],
    ) -> None:
        """Appends a timestamped structured audit record to the audit log."""
        if self._audit_handle is None and self.audit_log_path:
            try:
                parent_dir = os.path.dirname(self.audit_log_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                self._audit_handle = open(self.audit_log_path, "a", encoding="utf-8")
            except OSError as exc:
                logger.warning(
                    "Could not open audit log at %s: %s", self.audit_log_path, exc
                )
                return

        if self._audit_handle is None:
            return

        entry = {
            "timestamp": time.time(),
            "type": record_type,
            "state": str(state),
            "payload": payload,
        }
        try:
            self._audit_handle.write(json.dumps(entry, sort_keys=True) + "\n")
            self._audit_handle.flush()
        except Exception as exc:
            logger.warning("Failed to write audit record: %s", exc)

    def close(self) -> None:
        """Flushes and closes open file handles."""
        if self._audit_handle is not None:
            try:
                self._audit_handle.flush()
                self._audit_handle.close()
            except Exception:
                pass
            self._audit_handle = None
