from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_LOG_BYTES = 1_000_000
MAX_ENTRIES = 200
_LOG_LOCK = threading.Lock()
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(password|passwd|pass|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+"), r"\1=<redacted>"),
    (re.compile(r"(?i)(https?://)([^/\s:@]+):([^@\s]+)@"), r"\1<redacted>@"),
    (re.compile(r"(?i)([?&](?:password|passwd|pass|token|secret|api[_-]?key)=)[^&\s]+"), r"\1<redacted>"),
)


def classify_error(error: BaseException | str) -> str:
    message = str(error).casefold()
    if "bad cpu type" in message or "incompatible architecture" in message:
        return "runtime-arkitektur"
    if "session" in message or "login" in message or "adgangskod" in message:
        return "session-udløbet"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "connection" in message or "forbind" in message or "network" in message:
        return "netværk"
    if "calendar" in message or "kalender" in message or "arbejdskalender" in message:
        return "selfservice-kalender"
    return "ukendt"


def sanitize_error_message(message: str) -> str:
    sanitized = " ".join(str(message).strip().split())
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized[:1000] or "Ukendt fejl"


def _rotate_if_needed(path: Path) -> None:
    if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
        rotated = path.with_suffix(path.suffix + ".1")
        rotated.unlink(missing_ok=True)
        path.replace(rotated)


def record_error(
    path: Path,
    component: str,
    error: BaseException | str,
    context: dict[str, Any] | None = None,
) -> None:
    """Append a sanitized diagnostic entry without allowing logging to break the app."""
    try:
        message = sanitize_error_message(str(error))
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": sanitize_error_message(component)[:80],
            "error_type": type(error).__name__ if isinstance(error, BaseException) else "Error",
            "category": classify_error(error),
            "message": message,
            "context": {
                str(key): sanitize_error_message(str(value))[:160]
                for key, value in (context or {}).items()
                if value is not None
            },
        }
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return


def record_diagnostic(path: Path, component: str, context: dict[str, Any] | None = None) -> None:
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": sanitize_error_message(component)[:80],
            "event_type": "diagnostic",
            "context": {
                str(key): sanitize_error_message(str(value))[:160]
                for key, value in (context or {}).items()
                if value is not None
            },
        }
        with _LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return


def read_recent_errors(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    try:
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-MAX_ENTRIES:]:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return list(reversed(entries[-max(1, limit):]))
    except OSError:
        return []


def split_recent_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors = [entry for entry in entries if entry.get("event_type") != "diagnostic"][:5]
    sync_timings = [
        entry for entry in entries
        if entry.get("event_type") == "diagnostic" and entry.get("component") == "sync-timing"
    ][:3]
    return errors, sync_timings
