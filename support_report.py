"""Fejlrapport, som brugeren selv vælger at sende til udvikleren.

Indeholder kun app- og styresystemoplysninger og app-loggen. Alt, der kan pege på en
person (chauffførnummer, login, brugernavn, computernavn, IP, e-mail, kalender-token),
erstattes, før teksten vises eller sendes.
"""
from __future__ import annotations

import getpass
import os
import platform
import re
import socket
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable

_GENERIC_PATTERNS = (
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "<email>"),
    (re.compile(r"(?i)(/Users/|/home/|[A-Z]:\\Users\\)[^/\\\s]+"), r"\1<bruger>"),
    (re.compile(r"\b(?!127\.0\.0\.1\b)(?!0\.0\.0\.0\b)(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"(?i)([?&](?:token|pass(?:word)?|secret|key)=)[^&\s\"']+"), r"\1<skjult>"),
)


def scrub(text: str, sensitive: Iterable[str]) -> str:
    # Længste værdier først, så "16134" ikke ødelægger en længere værdi, der indeholder det.
    for value in sorted({str(v).strip() for v in sensitive if v and len(str(v).strip()) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(value), "<skjult>", text, flags=re.IGNORECASE)
    for pattern, replacement in _GENERIC_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def local_identifiers() -> list[str]:
    values: list[str] = []
    for getter in (getpass.getuser, socket.gethostname, lambda: Path.home().name):
        try:
            values.append(str(getter()))
        except Exception:
            pass
    values += [v.split(".")[0] for v in values if "." in v]
    return values


def playwright_browser_status() -> str:
    try:
        version = metadata.version("playwright")
    except metadata.PackageNotFoundError:
        return "Playwright: ikke installeret"
    custom = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if custom:
        root = Path(custom)
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "ms-playwright"
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    else:
        root = Path.home() / ".cache" / "ms-playwright"
    try:
        installed = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        installed = []
    return f"Playwright {version}; installerede browsere: {', '.join(installed) or 'ingen'}"


def _profile_lines(index: int, settings: dict[str, Any]) -> list[str]:
    return [
        f"Profil {index}:",
        f"  arbejdstype: {settings.get('employment_type', '')}",
        f"  dage frem: {settings.get('days_ahead', '')}",
        f"  auto-sync: {'til' if settings.get('automatic_sync_enabled', True) else 'fra'}",
        f"  SelfService-session bekræftet: {'ja' if settings.get('selfservice_session_verified') else 'nej'}",
        f"  seneste auto-sync: {settings.get('last_automatic_sync_status', 'aldrig')} "
        f"{settings.get('last_automatic_sync_attempt_at', '')}".rstrip(),
        f"  seneste auto-sync-besked: {settings.get('last_automatic_sync_message', '') or '-'}",
        f"  systembesked: {'til' if settings.get('notify_on_changes', True) else 'fra'}, "
        f"push: {'til' if settings.get('push_enabled') else 'fra'}",
        f"  offentlig kalenderadresse sat: {'ja' if settings.get('calendar_public_base_url') else 'nej'}",
    ]


def _log_line(entry: dict[str, Any], profile_labels: dict[str, str]) -> str:
    context = dict(entry.get("context") or {})
    driver_id = str(context.pop("driver_id", "") or "")
    if driver_id:
        context = {"profil": profile_labels.get(driver_id, "ukendt"), **context}
    detail = entry.get("message") or ""
    extra = ", ".join(f"{k}={v}" for k, v in context.items())
    kind = entry.get("category") or entry.get("event_type") or ""
    error_type = entry.get("error_type") or ""
    return f"{entry.get('timestamp', '')} | {entry.get('component', '')} | {kind} {error_type}: {detail}" + (
        f" [{extra}]" if extra else ""
    )


def build_support_report(
    *,
    version: str,
    commit: str,
    profiles: dict[str, dict[str, Any]],
    log_entries: list[dict[str, Any]],
    runtime: dict[str, Any],
    port: int | str,
    comment: str = "",
) -> str:
    profile_labels = {driver_id: f"Profil {i}" for i, driver_id in enumerate(sorted(profiles), start=1)}
    lines = [
        "RosterMate fejlrapport",
        f"Version: {version} (commit {commit})",
        f"Styresystem: {platform.system()} {platform.release()} ({platform.machine()})",
        f"Python: {runtime.get('python_version', platform.python_version())}",
        f"Python-arkitektur: {runtime.get('machine', '')}; Playwright-node: {runtime.get('playwright_node_architecture', '')}",
        playwright_browser_status(),
        f"Lokal port: {port}",
        f"Antal profiler: {len(profiles)}",
        "",
    ]
    for driver_id in sorted(profiles):
        lines += _profile_lines(int(profile_labels[driver_id].split()[-1]), profiles[driver_id])
    lines += ["", f"Seneste loglinjer ({len(log_entries)}, nyeste først):"]
    lines += [_log_line(entry, profile_labels) for entry in log_entries] or ["Ingen registrerede fejl."]
    if comment.strip():
        lines += ["", "Brugerens beskrivelse:", comment.strip()[:2000]]

    sensitive: list[str] = list(profiles) + local_identifiers()
    for settings in profiles.values():
        sensitive += [
            str(settings.get(key) or "")
            for key in ("user", "pass", "calendar_access_token", "push_topic")
        ]
        public = str(settings.get("calendar_public_base_url") or "")
        sensitive.append(re.sub(r"^https?://", "", public).split("/")[0])
    return scrub("\n".join(lines) + "\n", sensitive)
