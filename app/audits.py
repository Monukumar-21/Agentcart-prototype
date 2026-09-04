"""
audits.py -- the audit / log manager. Append-only JSONL file: one line per
money-related action, whether it was allowed or blocked. Nothing touches
Razorpay without a line being written first (see orchestrator.py).
"""

from __future__ import annotations
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schema import AuditEntry

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
LOG_PATH = _DATA_DIR / "audit.log"

_lock = threading.Lock()


class AuditLogger:
    def __init__(self, path: Path = LOG_PATH) -> None:
        self.path = path
        self.path.touch(exist_ok=True)

    def log(
        self,
        *,
        actor: str,
        tool: str,
        params: dict[str, Any],
        decision: str,
        reason: str,
        result: Optional[dict[str, Any]] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            ts=datetime.now(timezone.utc).isoformat(),
            actor=actor or "unknown-agent",
            tool=tool,
            params=params,
            decision=decision,
            reason=reason,
            result=result,
        )
        with _lock:
            with self.path.open("a") as f:
                f.write(entry.model_dump_json() + "\n")
        return entry

    def all_entries(self) -> list[AuditEntry]:
        with _lock:
            raw = self.path.read_text().strip()
        if not raw:
            return []
        entries = [AuditEntry.model_validate_json(line) for line in raw.splitlines()]
        return list(reversed(entries))  # newest first

    def stats(self) -> dict[str, int]:
        entries = self.all_entries()
        allowed = sum(1 for e in entries if e.decision == "allowed")
        blocked = sum(1 for e in entries if e.decision == "blocked")
        return {"total": len(entries), "allowed": allowed, "blocked": blocked}


audit_logger = AuditLogger()
