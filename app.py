from __future__ import annotations

import json
import os
import re
import secrets
import socket
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, session, url_for

from automatic_sync import (
    LAST_ATTEMPT_KEY,
    automatic_sync_slot,
    ensure_automatic_sync_times,
    next_automatic_sync,
    schedule_summary,
)
from dashboard import should_show_first_run, should_show_welcome_back
from credentials import get_password, set_password
from launch_agent import sync_launch_agent_preference
from login import launch_authenticated_context, login_manager, read_stable_page_content, save_session_storage
from port_config import configured_port, port_is_available, save_port, valid_port
from release_update import check_for_release_update
from session_store import SelfServiceSessionStore
from settings import apply_wizard_preferences, with_setup_defaults
from sync import build_sync_preview, fetch_status_is_error, run_initial_sync
from wizard import FIRST_RUN_TEMPLATE, WIZARD_PREFERENCES_TEMPLATE

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "rostermate-dev-secret-change-me")

BASE_DIR = Path(__file__).resolve().parent


def default_storage_root(platform_name: str | None = None) -> Path:
    configured_root = os.environ.get("ROSTERMATE_HOME", "").strip()
    if configured_root:
        return Path(configured_root).expanduser()
    active_platform = platform_name or sys.platform
    if active_platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "RosterMate"
        return Path.home() / "AppData" / "Local" / "RosterMate"
    return BASE_DIR


STORAGE_ROOT = default_storage_root()
DATA_DIR = STORAGE_ROOT / "data"
BACKUP_DIR = STORAGE_ROOT / "backups"
OUTPUT_DIR = STORAGE_ROOT / "output"
HISTORY_PATH = DATA_DIR / "history.json"
PLAN_PATH = DATA_DIR / "plan.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
SCHEDULE_PATH = OUTPUT_DIR / "schedule.json"
EVENTS_STORE_PATH = OUTPUT_DIR / "events_store.json"
CHANGES_PATH = OUTPUT_DIR / "changes.json"
ICS_PATH = OUTPUT_DIR / "vagter.ics"
LOCAL_TIMEZONE = "Europe/Copenhagen"
APP_VERSION = "1.12.0"
SYNC_LOCKS: dict[str, threading.Lock] = {}
SYNC_LOCKS_GUARD = threading.Lock()


def driver_sync_lock(driver_id: str) -> threading.Lock:
    with SYNC_LOCKS_GUARD:
        return SYNC_LOCKS.setdefault(driver_id, threading.Lock())


def fetch_schedule_with_retry(days_ahead: int, driver_id: str, attempts: int = 2) -> tuple[list[dict[str, Any]], str]:
    last_result: tuple[list[dict[str, Any]], str] = ([], "SelfService kunne ikke kontaktes")
    for attempt in range(max(1, attempts)):
        last_result = fetch_selfservice_schedule(days_ahead, driver_id)
        events, message = last_result
        if events or not fetch_status_is_error(message):
            return last_result
        if attempt + 1 < attempts:
            time.sleep(1)
    return last_result


def application_port() -> int:
    return configured_port(root=DATA_DIR.parent)


def ui_platform_labels(platform_name: str | None = None) -> dict[str, str]:
    active_platform = platform_name or sys.platform
    if active_platform == "win32":
        return {
            "local_device": "På denne Windows-pc",
            "autostart": "Start automatisk med Windows",
            "credential_store": "Windows Credential Manager",
        }
    return {
        "local_device": "På denne Mac",
        "autostart": "Start automatisk med macOS",
        "credential_store": "macOS-nøgleringen",
    }


def is_loopback_request() -> bool:
    remote_address = request.remote_addr
    if remote_address in {"127.0.0.1", "::1", None}:
        forwarded_address = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
        if forwarded_address:
            return forwarded_address in {"127.0.0.1", "::1"}
        return True
    return False


@app.before_request
def protect_lan_routes() -> Any:
    if is_loopback_request():
        return None
    if request.endpoint == "calendar_file" and request.view_args:
        driver_id = normalize_driver_id(str(request.view_args.get("driver_id", "")))
        expected_token = str(load_settings(driver_id).get("calendar_access_token") or "")
        supplied_token = str(request.args.get("token") or "")
        if expected_token and secrets.compare_digest(expected_token, supplied_token):
            return None
    return jsonify({"status": "error", "message": "Kun kalenderlinket er tilgængeligt på lokalnetværket"}), 403


def normalize_driver_id(value: str) -> str:
    driver_id = str(value).strip()
    if not re.fullmatch(r"\d{1,12}", driver_id):
        raise ValueError("Ugyldigt chaufførnummer")
    return driver_id


def software_info(project_dir: Path | None = None) -> dict[str, str]:
    root = project_dir or BASE_DIR
    commit = "ukendt"
    updated_at = "ukendt"
    try:
        commit_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        date_result = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if commit_result.returncode == 0 and commit_result.stdout.strip():
            commit = commit_result.stdout.strip()
        if date_result.returncode == 0 and date_result.stdout.strip():
            updated_at = format_timestamp(date_result.stdout.strip())
    except OSError:
        pass
    return {"version": APP_VERSION, "commit": commit, "updated_at": updated_at}


def driver_storage_paths(driver_id: str) -> dict[str, Path]:
    safe_driver_id = normalize_driver_id(driver_id)
    data_dir = DATA_DIR / safe_driver_id
    backup_dir = BACKUP_DIR / safe_driver_id
    output_dir = OUTPUT_DIR / safe_driver_id
    return {
        "driver_id": Path(safe_driver_id),
        "data_dir": data_dir,
        "backup_dir": backup_dir,
        "output_dir": output_dir,
        "history_path": data_dir / "history.json",
        "plan_path": data_dir / "plan.json",
        "settings_path": data_dir / "settings.json",
        "schedule_path": output_dir / "schedule.json",
        "events_store_path": output_dir / "events_store.json",
        "changes_path": output_dir / "changes.json",
        "ics_path": output_dir / "vagter.ics",
        "selfservice_storage_state_path": data_dir / "selfservice_storage_state.json",
        "selfservice_user_data_dir": data_dir / "selfservice-browser",
    }


def ensure_storage(driver_id: str | None = None) -> dict[str, Path] | None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if driver_id is None:
        return None

    paths = driver_storage_paths(driver_id)
    paths["data_dir"].mkdir(parents=True, exist_ok=True)
    paths["backup_dir"].mkdir(parents=True, exist_ok=True)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)
    paths["history_path"].touch(exist_ok=True)
    paths["plan_path"].touch(exist_ok=True)
    paths["settings_path"].touch(exist_ok=True)
    paths["schedule_path"].touch(exist_ok=True)
    paths["events_store_path"].touch(exist_ok=True)
    paths["changes_path"].touch(exist_ok=True)
    paths["ics_path"].touch(exist_ok=True)
    return paths


def get_driver_paths(driver_id: str) -> dict[str, Path]:
    try:
        return ensure_storage(driver_id) or driver_storage_paths(driver_id)
    except ValueError:
        abort(404)


def list_driver_ids() -> list[str]:
    if not DATA_DIR.exists():
        return []
    driver_ids: list[str] = []
    for path in DATA_DIR.iterdir():
        settings_path = path / "settings.json"
        if path.is_dir() and path.name.isdigit() and settings_path.exists() and settings_path.stat().st_size > 0:
            driver_ids.append(path.name)
    return sorted(driver_ids, key=lambda value: int(value))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def save_history(history: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or HISTORY_PATH
    save_json(target, history)


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or HISTORY_PATH
    return load_json(target, [])


def load_plan(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or PLAN_PATH
    return load_json(target, [])


def save_plan(plan: list[dict[str, Any]], path: Path | None = None) -> None:
    target = path or PLAN_PATH
    save_json(target, plan)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def remove_env_secret(env_path: Path, key_to_remove: str) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line.split("=", 1)[0].strip() != key_to_remove]
    env_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")


def load_settings(driver_id: str) -> dict[str, Any]:
    paths = get_driver_paths(driver_id)
    env_values = {}
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_values[key.strip()] = value.strip().strip('"').strip("'")

    stored = load_json(paths["settings_path"], {})
    legacy_password = str(stored.get("pass", "") or "")
    if legacy_password:
        try:
            set_password(driver_id, legacy_password)
        except Exception:
            pass
        else:
            stored = {key: value for key, value in stored.items() if key != "pass"}
            save_json(paths["settings_path"], stored)
    env_password = str(env_values.get("SELFSERVICE_PASS", "") or "")
    if env_password:
        try:
            set_password(driver_id, env_password)
        except Exception:
            pass
        else:
            remove_env_secret(env_path, "SELFSERVICE_PASS")
            env_values.pop("SELFSERVICE_PASS", None)
    env_user = str(env_values.get("SELFSERVICE_USER", "") or "").strip()
    if env_user.casefold() in {"dit-brugernavn", "your-username", "username"}:
        remove_env_secret(env_path, "SELFSERVICE_USER")
        env_values.pop("SELFSERVICE_USER", None)
        env_user = ""
    try:
        days_ahead = int(stored.get("days_ahead", env_values.get("DAYS_AHEAD", 7)))
    except (TypeError, ValueError):
        days_ahead = 7

    employment_type = stored.get("employment_type", "ramme_ansat")
    if employment_type not in ("ramme_ansat", "fast_turnus", "timeloennet"):
        employment_type = "ramme_ansat"

    loaded = with_setup_defaults({
        **stored,
        "url": stored.get("url") or env_values.get("SELFSERVICE_URL", "https://selfservicedanmark.tidebus.dk"),
        "user": stored.get("user") or env_user,
        "pass": get_password(driver_id) or stored.get("pass", ""),
        "days_ahead": max(1, min(days_ahead, 365)),
        "remove_old_shifts": _coerce_bool(
            stored.get("remove_old_shifts", env_values.get("REMOVE_OLD_SHIFTS", False))
        ),
        "employment_type": employment_type,
    })
    loaded, schedule_changed = ensure_automatic_sync_times(loaded)
    if schedule_changed:
        persisted = dict(loaded)
        persisted.pop("pass", None)
        save_json(paths["settings_path"], persisted)
    return loaded


def save_driver_settings(driver_id: str, settings: dict[str, Any]) -> None:
    paths = get_driver_paths(driver_id)
    sanitized = dict(settings)
    sanitized.pop("pass", None)
    save_json(paths["settings_path"], sanitized)


def driver_urls(driver_id: str) -> dict[str, str]:
    safe_driver_id = normalize_driver_id(driver_id)
    base_path = f"/{safe_driver_id}"
    return {
        "base_path": base_path,
        "dashboard_url": f"{base_path}/",
        "wizard_url": f"{base_path}/wizard",
        "wizard_relogin_url": f"{base_path}/wizard?relogin=1",
        "wizard_connect_url": f"{base_path}/wizard/connect",
        "wizard_status_url": f"{base_path}/wizard/status",
        "wizard_test_connection_url": f"{base_path}/wizard/test-connection",
        "wizard_preferences_url": f"{base_path}/wizard/preferences",
        "wizard_complete_url": f"{base_path}/wizard/complete",
        "settings_url": f"{base_path}/settings-page",
        "history_url": f"{base_path}/history",
        "sync_url": f"{base_path}/sync",
        "settings_post_url": f"{base_path}/settings",
        "calendar_url": f"{base_path}/calendar.ics",
    }


def calculate_next_sync(settings: dict[str, Any], now: datetime | None = None) -> str:
    """Format the next stable per-profile automatic synchronization time."""
    current = now or datetime.now()
    weekday_names = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
    next_sync = next_automatic_sync(settings, current)
    if next_sync is None:
        return "Afventer næste vindue"
    return f"{weekday_names[next_sync.weekday()]} kl. {next_sync.strftime('%H:%M')}"


def format_timestamp(value: str | None) -> str:
    if not value:
        return "Aldrig"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y kl. %H:%M")
    except ValueError:
        return value


def extract_shift_name(title: str) -> str:
    if "ID:" not in title:
        return title or "Ukendt"
    id_match = re.search(r"ID:\s+([A-Za-z_]+)", title)
    if id_match:
        return id_match.group(1).replace("_", " ")
    return title


def extract_time_label(event: dict[str, Any]) -> str:
    if event.get("all_day"):
        return "Hele dagen"
    start_value = event.get("start", "")
    end_value = event.get("end", "")
    start_time = start_value.split("T", 1)[1][:5] if "T" in start_value else ""
    end_time = end_value.split("T", 1)[1][:5] if "T" in end_value else ""
    if start_time and end_time:
        return f"{start_time} - {end_time}"
    if start_time:
        return start_time
    return "Tid ukendt"


def classify_shift(event: dict[str, Any]) -> tuple[str, str, str]:
    title = extract_shift_name(str(event.get("title", "Ukendt"))).strip()
    normalized = title.lower()
    if any(token in normalized for token in ["fri", "stregdag"]):
        return "Fridag", "type-off", "fri"
    if "vacation" in normalized or "ferie" in normalized:
        return "Ferie", "type-vacation", "palme"
    return "Vagt", "type-work", title[:1].upper() if title else "V"


def build_week_navigation(events: list[dict[str, Any]], week_offset: int) -> dict[str, Any]:
    valid_dates: list[date] = []
    for event in events:
        shift_date = str(event.get("date", "")).strip()
        if not shift_date:
            continue
        try:
            valid_dates.append(date.fromisoformat(shift_date))
        except ValueError:
            continue

    today = date.today()
    current_week_start = today - timedelta(days=today.weekday())
    week_start = current_week_start + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    week_number = week_start.isocalendar().week

    if week_offset == 0:
        headline = "Denne uge"
    elif week_offset == 1:
        headline = "Næste uge"
    elif week_offset == -1:
        headline = "Sidste uge"
    else:
        headline = f"Uge {week_number}"

    min_date = min(valid_dates) if valid_dates else None
    max_date = max(valid_dates) if valid_dates else None

    return {
        "week_start": week_start,
        "week_end": week_end,
        "label": f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m')}",
        "headline": headline,
        "week_number": week_number,
        "has_previous": min_date is not None and week_start > min_date,
        "has_next": max_date is not None and week_end < max_date,
        "previous_offset": week_offset - 1,
        "next_offset": week_offset + 1,
        "is_current_week": week_offset == 0,
    }


def build_upcoming_shift_cards(events: list[dict[str, Any]], week_start: date, week_end: date) -> list[dict[str, Any]]:
    weekday_names = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
    grouped_days: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    days_by_date: dict[str, dict[str, Any]] = {}

    for event in sorted(events, key=lambda item: (item.get("date", ""), item.get("start", ""))):
        shift_date = str(event.get("date", "")).strip()
        if not shift_date:
            continue
        try:
            shift_dt = date.fromisoformat(shift_date)
        except ValueError:
            continue
        if shift_dt < week_start or shift_dt > week_end:
            continue

        title = str(event.get("title", "Ukendt"))
        time_label = extract_time_label(event)
        signature = (shift_date, title, time_label)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        if shift_date not in days_by_date:
            weekday = weekday_names[shift_dt.weekday()]
            date_label = shift_dt.strftime("%d.%m")
            is_today = shift_dt == date.today()

            day_entry: dict[str, Any] = {
                "weekday": weekday,
                "date_label": date_label,
                "is_today": is_today,
                "shifts": [],
            }
            grouped_days.append(day_entry)
            days_by_date[shift_date] = day_entry

        shift_type_label, shift_type_class, shift_icon = classify_shift(event)
        days_by_date[shift_date]["shifts"].append(
            {
                "title": extract_shift_name(title),
                "time_label": time_label,
                "variant": "all-day" if event.get("all_day") else "timed",
                "type_label": shift_type_label,
                "type_class": shift_type_class,
                "icon": shift_icon,
            }
        )

    return grouped_days


def select_next_calendar_events(
    events: list[dict[str, Any]],
    today: date | None = None,
    limit: int = 7,
) -> list[dict[str, Any]]:
    """Return every event from the next distinct calendar dates."""
    start_date = today or date.today()
    upcoming: list[dict[str, Any]] = []

    for event in events:
        shift_date = str(event.get("date", "")).strip()
        try:
            event_date = date.fromisoformat(shift_date)
        except ValueError:
            continue
        if event_date >= start_date:
            upcoming.append(event)

    sorted_events = sorted(
        upcoming,
        key=lambda item: (str(item.get("date", "")), str(item.get("start", ""))),
    )
    selected_dates: list[str] = []
    for event in sorted_events:
        shift_date = str(event.get("date", ""))
        if shift_date not in selected_dates:
            if len(selected_dates) >= max(0, limit):
                break
            selected_dates.append(shift_date)
    return [event for event in sorted_events if str(event.get("date", "")) in selected_dates]


def describe_change(change: dict[str, Any]) -> dict[str, str]:
    change_type = str(change.get("type", "changed"))
    labels = {
        "added": ("Tilføjet", "badge-added"),
        "removed": ("Fjernet", "badge-removed"),
        "changed": ("Opdateret", "badge-changed"),
    }
    badge_text, badge_class = labels.get(change_type, ("Ændret", "badge-changed"))

    identifier = str(change.get("id") or change.get("title") or "Vagt")
    item = change.get("item") if isinstance(change.get("item"), dict) else {}
    old_item = change.get("old") if isinstance(change.get("old"), dict) else {}
    new_item = change.get("new") if isinstance(change.get("new"), dict) else {}

    active_item = item or new_item or old_item
    title = extract_shift_name(str(active_item.get("title") or active_item.get("id") or identifier))
    date_label = str(active_item.get("date") or new_item.get("date") or old_item.get("date") or "")

    if change_type == "changed":
        before_label = extract_time_label(old_item) if old_item else "Tid ukendt"
        after_label = extract_time_label(new_item) if new_item else "Tid ukendt"
        detail = f"{before_label} -> {after_label}"
    else:
        detail = extract_time_label(active_item) if active_item else ""

    return {
        "badge_text": badge_text,
        "badge_class": badge_class,
        "title": title,
        "detail": detail,
        "date_label": date_label,
    }


def local_network_address() -> str:
    override = os.environ.get("ROSTERMATE_LAN_HOST", "").strip()
    if override:
        return override
    connection = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        connection.connect(("192.0.2.1", 80))
        return str(connection.getsockname()[0])
    except OSError:
        hostname = socket.gethostname().split(".")[0]
        return f"{hostname}.local"
    finally:
        connection.close()


def calendar_subscription_address(driver_id: str, token: str, public_base_url: str = "") -> str:
    base_url = str(public_base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = f"http://{local_network_address()}:{application_port()}"
    return f"{base_url}/{normalize_driver_id(driver_id)}/calendar.ics?token={token}"


def create_backup(source: Path, backup_dir: Path | None = None) -> Path:
    target_dir = backup_dir or BACKUP_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = target_dir / f"{source.stem}-{timestamp}.bak"
    shutil.copy2(source, backup_path)
    return backup_path


def build_event_from_shift(shift: dict[str, Any], shift_date: str) -> dict[str, Any]:
    title = shift.get("id") or shift.get("title") or "Ukendt"
    shift_from = str(shift.get("from", "")).strip()
    shift_to = str(shift.get("to", "")).strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", shift_from):
        shift_from = shift_from.zfill(5)
    if re.fullmatch(r"\d{1,2}:\d{2}", shift_to):
        shift_to = shift_to.zfill(5)
    shift_text = f"{title} {shift_from} {shift_to}".strip().lower()

    # Detektér all-day events: fridage, ferier, eller hvis begge tider er 00:00
    is_all_day = (
        any(token in shift_text for token in ["fri", "vacation", "stregdag"]) or
        (shift_from == "00:00" and shift_to == "00:00")
    )

    if is_all_day:
        start = f"{shift_date}T00:00:00"
        end = f"{shift_date}T23:59:59"
    else:
        start_time = shift_from or "00:00"
        end_time = shift_to or start_time
        start = f"{shift_date}T{start_time}:00"
        end = f"{shift_date}T{end_time}:00"

    if not is_all_day and shift_to and shift_to < shift_from:
        end_dt = datetime.fromisoformat(end) + timedelta(days=1)
        end = end_dt.strftime("%Y-%m-%dT%H:%M:%S")

    event_id = f"{shift_date}:{title}:{start}:{end}"
    return {
        "id": event_id,
        "title": title,
        "date": shift_date,
        "start": start,
        "end": end,
        "all_day": is_all_day,
    }


def _is_in_window(value: str | None, window_start: str, window_end: str) -> bool:
    if not value:
        return False
    return window_start <= value <= window_end


def sync_schedule(
    existing_events: list[dict[str, Any]],
    new_events: list[dict[str, Any]],
    window_start: str,
    window_end: str,
    remove_old_shifts: bool,
    output_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_dir = output_dir or OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    # SelfService is authoritative inside the requested window. Replace that
    # section completely so changed or removed duties cannot survive as stale
    # calendar entries. Outside the window, preserve history unless the user
    # explicitly asks to remove old shifts.
    preserved_events = (
        []
        if remove_old_shifts
        else [event for event in existing_events if not _is_in_window(event.get("date"), window_start, window_end)]
    )
    updated_events = list(preserved_events)
    seen_ids: set[str] = {str(event.get("id") or "") for event in updated_events}
    for event in new_events:
        if not _is_in_window(event.get("date"), window_start, window_end):
            continue
        event_id = str(event.get("id") or "")
        if event_id and event_id in seen_ids:
            continue
        updated_events.append(event)
        if event_id:
            seen_ids.add(event_id)
    updated_events.sort(key=lambda event: (str(event.get("date", "")), str(event.get("start", ""))))

    changes: list[dict[str, Any]] = []
    return updated_events, changes


def compare_plans(old_plan: list[dict[str, Any]], new_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_by_id = {item.get("id", item.get("title", "")): item for item in old_plan}
    new_by_id = {item.get("id", item.get("title", "")): item for item in new_plan}

    changes: list[dict[str, Any]] = []

    for shift_id in sorted(set(old_by_id) | set(new_by_id)):
        old_item = old_by_id.get(shift_id)
        new_item = new_by_id.get(shift_id)

        if old_item is None and new_item is not None:
            changes.append({"type": "added", "id": shift_id, "item": new_item})
        elif old_item is not None and new_item is None:
            changes.append({"type": "removed", "id": shift_id, "item": old_item})
        elif old_item is not None and new_item is not None and old_item != new_item:
            changes.append({"type": "changed", "id": shift_id, "old": old_item, "new": new_item})

    return changes


def _escape_ics_text(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def _ics_event_lines(event: dict[str, Any], timestamp: str) -> list[str]:
    event_date = str(event.get("date") or "")
    start_value = str(event.get("start") or "")
    end_value = str(event.get("end") or "")
    lines = ["BEGIN:VEVENT", f"UID:{_escape_ics_text(event.get('id', 'event'))}@rostermate.local", f"DTSTAMP:{timestamp}"]

    if event.get("all_day"):
        try:
            start_date = date.fromisoformat(event_date or start_value[:10])
        except ValueError:
            return []
        try:
            end_date = date.fromisoformat(end_value[:10])
        except ValueError:
            end_date = start_date + timedelta(days=1)
        if end_date <= start_date or "T" in end_value:
            end_date = start_date + timedelta(days=1)
        lines.extend([f"DTSTART;VALUE=DATE:{start_date:%Y%m%d}", f"DTEND;VALUE=DATE:{end_date:%Y%m%d}"])
    else:
        try:
            start = datetime.fromisoformat(start_value)
            end = datetime.fromisoformat(end_value)
        except ValueError:
            return []
        local_timezone = ZoneInfo(LOCAL_TIMEZONE)
        if start.tzinfo is None:
            start = start.replace(tzinfo=local_timezone)
        if end.tzinfo is None:
            end = end.replace(tzinfo=local_timezone)
        lines.extend(
            [
                f"DTSTART:{start.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
                f"DTEND:{end.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
            ]
        )

    lines.extend([f"SUMMARY:{_escape_ics_text(event.get('title', 'Vagt'))}", "END:VEVENT"])
    return lines


def write_outputs(events: list[dict[str, Any]], changes: list[dict[str, Any]], output_dir: Path | None = None) -> None:
    target_dir = output_dir or OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    save_json(target_dir / "events_store.json", events)
    save_json(target_dir / "changes.json", changes)
    save_json(target_dir / "schedule.json", events)

    ics_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RosterMate//DA",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:RosterMate",
    ]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for event in events:
        ics_lines.extend(_ics_event_lines(event, timestamp))
    ics_lines.append("END:VCALENDAR")
    (target_dir / "vagter.ics").write_bytes(("\r\n".join(ics_lines) + "\r\n").encode("utf-8"))


def parse_selfservice_calendar_pages(
    html_pages: list[str],
    window_start: date,
    window_end: date,
) -> list[dict[str, Any]]:
    from bs4 import BeautifulSoup

    events: list[dict[str, Any]] = []
    seen_events: set[tuple[str, str, str, str]] = set()

    for html in html_pages:
        soup = BeautifulSoup(html, "html.parser")
        for workday in soup.select("[data-workday-date]"):
            raw_date = str(workday.get("data-workday-date") or "")
            try:
                shift_date = datetime.strptime(raw_date, "%Y%m%d").date()
            except ValueError:
                continue
            if not window_start <= shift_date <= window_end:
                continue

            assignment = workday.select_one(".AssignmentsView")
            if assignment is None:
                continue
            assignment_text = assignment.get_text(" ", strip=True)
            normalized_text = assignment_text.casefold()
            shift: dict[str, Any] | None = None

            for all_day_title in ("Fri", "Vacation", "Stregdag"):
                if re.search(rf"\b{re.escape(all_day_title.casefold())}\b", normalized_text):
                    shift = {"id": all_day_title, "from": "00:00", "to": "00:00"}
                    break

            if shift is None:
                id_match = re.search(r"\bID:\s*([^\s]+)", assignment_text, re.IGNORECASE)
                from_match = re.search(r"\bFra:\s*(\d{1,2}:\d{2})", assignment_text, re.IGNORECASE)
                to_match = re.search(r"\bTil:\s*(\d{1,2}:\d{2})", assignment_text, re.IGNORECASE)
                if id_match and from_match and to_match:
                    shift = {
                        "id": id_match.group(1),
                        "from": from_match.group(1),
                        "to": to_match.group(1),
                    }

            if shift is None:
                continue
            event = build_event_from_shift(shift, shift_date.isoformat())
            event["raw"] = assignment_text
            event_key = (
                str(event.get("date", "")),
                str(event.get("title", "")),
                str(event.get("start", "")),
                str(event.get("end", "")),
            )
            if event_key not in seen_events:
                seen_events.add(event_key)
                events.append(event)

    return sorted(events, key=lambda event: (str(event.get("date", "")), str(event.get("start", ""))))


def displayed_selfservice_month(page: Any) -> tuple[int, int]:
    page.wait_for_selector("#Calendar", state="attached", timeout=30000)
    calendar = page.locator("#Calendar")
    year = int(calendar.get_attribute("data-year") or 0)
    month = int(calendar.get_attribute("data-month") or 0)
    if year < 2000 or month not in range(1, 13):
        raise RuntimeError("SelfService-kalenderens viste måned kunne ikke aflæses")
    return year, month


def open_selfservice_calendar(page: Any, selfservice_url: str) -> None:
    """Open Assignments when a valid session lands on the SelfService home page."""
    try:
        page.wait_for_selector("#Calendar", state="attached", timeout=5000)
        return
    except Exception:
        pass

    if selfservice_login_form_visible(page):
        raise RuntimeError("SelfService-sessionen er udløbet. Forbind til SelfService igen i opsætningsguiden.")

    assignments_url = urljoin(selfservice_url.rstrip("/") + "/", "Assignments")
    page.goto(assignments_url, wait_until="domcontentloaded")
    try:
        page.wait_for_selector("#Loading", state="hidden", timeout=15000)
    except Exception:
        pass

    if selfservice_login_form_visible(page):
        raise RuntimeError("SelfService-sessionen er udløbet. Forbind til SelfService igen i opsætningsguiden.")
    page.wait_for_selector("#Calendar", state="attached", timeout=30000)


def navigate_selfservice_month(page: Any, target_year: int, target_month: int) -> None:
    """Navigate the employee calendar without assuming its initial month or exact layout."""
    target = (target_year, target_month)
    for _ in range(18):
        current = displayed_selfservice_month(page)
        if current == target:
            return

        forward = current < target
        selector = (
            "#NextMonth:visible, #MonthAndYearSelectorAndNavigators .CalendarNextPeriod:visible"
            if forward
            else "#PreviousMonth:visible, #MonthAndYearSelectorAndNavigators .CalendarPreviousPeriod:visible"
        )
        clicked = False
        try:
            page.locator(selector).first.click(timeout=15000)
            clicked = True
        except Exception:
            clicked = bool(
                page.evaluate(
                    """target => {
                        const input = document.querySelector('#MonthAndYearSelectorKendoDDList');
                        const widget = input && window.jQuery
                            ? window.jQuery(input).data('kendoDropDownList')
                            : null;
                        if (!widget || !widget.dataSource) return false;
                        const item = widget.dataSource.data().find(value =>
                            Number(value.Year) === target.year && Number(value.Month) === target.month
                        );
                        if (!item) return false;
                        widget.value(item.Value);
                        widget.trigger('change');
                        return true;
                    }""",
                    {"year": target_year, "month": target_month},
                )
            )
        if not clicked:
            raise RuntimeError("SelfService viste ingen brugbar månedsnavigation")

        page.wait_for_function(
            """previous => {
                const calendar = document.querySelector('#Calendar');
                return calendar && (
                    Number(calendar.dataset.year) !== previous.year
                    || Number(calendar.dataset.month) !== previous.month
                );
            }""",
            arg={"year": current[0], "month": current[1]},
            timeout=30000,
        )
        try:
            page.wait_for_selector("#Loading", state="hidden", timeout=15000)
        except Exception:
            pass

    raise RuntimeError(f"SelfService kunne ikke navigere til {target_month:02d}/{target_year}")


def selfservice_login_form_visible(page: Any) -> bool:
    # Tide keeps parts of the login form in the DOM after a successful
    # client-side transition. Only visible fields mean that login is still
    # required.
    return page.locator("input#Username:visible, input#Password:visible").count() > 0


def selfservice_authenticated_marker_visible(page: Any) -> bool:
    return page.locator(
        "#Calendar:visible, #NextMonth:visible, "
        "input[type='checkbox'][id*='View']:visible"
    ).count() > 0


def perform_background_selfservice_login(page: Any, settings: dict[str, Any]) -> None:
    username = str(settings.get("user", "") or "").strip()
    password = str(settings.get("pass", "") or "")
    if not username or not password:
        raise RuntimeError(
            "De gemte SelfService-loginoplysninger mangler. Indtast brugernavn og adgangskode i opsætningsguiden."
        )

    username_field = page.locator("input#Username")
    username_field.fill(username)
    password_field = page.locator("input#Password")
    password_field.fill(password)
    login_button = page.locator(
        "#LoginButton, div.DarkButton, button[type='submit'], input[type='submit']"
    ).first
    try:
        login_button.click(timeout=15000)
    except Exception as exc:
        try:
            password_field.press("Enter")
        except Exception as fallback_exc:
            raise RuntimeError("SelfService-loginformularen kunne ikke indsendes.") from fallback_exc

    try:
        page.wait_for_function(
            """() => {
                const visible = (element) => Boolean(
                    element
                    && element.getClientRects().length
                    && getComputedStyle(element).visibility !== 'hidden'
                    && getComputedStyle(element).display !== 'none'
                );
                return [
                    document.querySelector('#Calendar'),
                    document.querySelector('#NextMonth'),
                    document.querySelector("input[type='checkbox'][id*='View']"),
                    document.querySelector('.validation-summary-errors'),
                    document.querySelector('.field-validation-error'),
                    document.querySelector('.error')
                ].some(visible);
            }""",
            timeout=30000,
        )
    except Exception:
        pass
    if selfservice_authenticated_marker_visible(page):
        return
    if selfservice_login_form_visible(page):
        raise RuntimeError(
            "SelfService afviste login eller sendte tilbage til login-siden. Kontrollér brugernavn og adgangskode i opsætningsguiden."
        )


def fetch_selfservice_schedule(
    days_ahead: int,
    driver_id: str,
    *,
    allow_credential_login: bool = True,
    headless: bool = True,
    hide_window: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    paths = get_driver_paths(driver_id)
    settings = load_settings(driver_id)
    session_store = SelfServiceSessionStore.from_paths(driver_id, paths)

    try:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return [], f"Afhængighed mangler: {exc}"

    html_pages: list[str] = []
    try:
        with sync_playwright() as p:
            browser, context = launch_authenticated_context(
                p,
                session_store,
                headless=headless,
                hide_window=hide_window,
            )
            page = context.new_page()
            page.set_default_timeout(30000)

            page.goto(settings["url"], wait_until="load")

            initial_html = read_stable_page_content(page)
            if initial_html is None:
                context.close()
                if browser is not None:
                    browser.close()
                return [], "SelfService navigerer stadig. Prøv synkroniseringen igen om et øjeblik."
            debug_path = paths["output_dir"] / "debug_initial.log"
            with debug_path.open("w", encoding="utf-8") as f:
                f.write(initial_html[:10000])

            if selfservice_login_form_visible(page):
                if not allow_credential_login:
                    context.close()
                    if browser is not None:
                        browser.close()
                    return [], "SelfService-sessionen er udløbet"
                try:
                    perform_background_selfservice_login(page, settings)
                except Exception:
                    try:
                        page.screenshot(
                            path=str(paths["output_dir"] / "debug_login_failure.png"),
                            full_page=True,
                        )
                    except Exception:
                        pass
                    raise

                try:
                    page.wait_for_selector("#Loading", state="hidden", timeout=15000)
                except:
                    pass

                try:
                    page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    pass
                save_session_storage(page, session_store)
                context.storage_state(path=str(session_store.storage_state_path), indexed_db=True)

                try:
                    page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                    page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass

                try:
                    all_checkboxes = page.locator("input[type='checkbox'][id*='View']")
                    count = all_checkboxes.count()

                    for i in range(min(count, 10)):
                        try:
                            checkbox = all_checkboxes.nth(i)
                            if not checkbox.is_checked(timeout=1000):
                                checkbox.click(timeout=2000)
                                try:
                                    page.wait_for_load_state("networkidle", timeout=2000)
                                except:
                                    pass
                        except:
                            pass
                except:
                    pass

            try:
                open_selfservice_calendar(page, settings["url"])
            except Exception as exc:
                if selfservice_login_form_visible(page):
                    try:
                        perform_background_selfservice_login(page, settings)
                        open_selfservice_calendar(page, settings["url"])
                    except Exception as retry_exc:
                        exc = retry_exc
                if not isinstance(exc, RuntimeError):
                    exc = RuntimeError("SelfService viste ikke arbejdskalenderen efter login.")
                context.close()
                if browser is not None:
                    browser.close()
                return [], f"SelfService-kalenderen kunne ikke åbnes: {exc}"

            today_month = date.today().replace(day=1)
            try:
                navigate_selfservice_month(page, today_month.year, today_month.month)
            except Exception as exc:
                context.close()
                if browser is not None:
                    browser.close()
                return [], f"Login virkede, men SelfService-kalenderen kunne ikke åbnes: {exc}"

            html = read_stable_page_content(page)
            if html is None:
                context.close()
                if browser is not None:
                    browser.close()
                return [], "SelfService navigerer stadig. Prøv synkroniseringen igen om et øjeblik."

            html_pages.append(html)
            window_end = date.today() + timedelta(days=days_ahead)
            current_month = date.today().replace(day=1)
            final_month = window_end.replace(day=1)
            while current_month < final_month:
                if current_month.month == 12:
                    current_month = current_month.replace(year=current_month.year + 1, month=1)
                else:
                    current_month = current_month.replace(month=current_month.month + 1)
                try:
                    navigate_selfservice_month(page, current_month.year, current_month.month)
                    month_html = read_stable_page_content(page)
                    if month_html is not None:
                        html_pages.append(month_html)
                except Exception as exc:
                    context.close()
                    if browser is not None:
                        browser.close()
                    return [], f"Kunne ikke hente {current_month:%m/%Y} fra SelfService: {exc}"

            debug_path = paths["output_dir"] / "debug_html.log"
            with debug_path.open("w", encoding="utf-8") as f:
                f.write("\n<!-- ROSTERMATE MONTH BREAK -->\n".join(html_pages)[:300000])

            context.close()
            if browser is not None:
                browser.close()

    except Exception as exc:
        return [], f"Fejl ved henting af schedule: {str(exc)}"

    if not html_pages:
        return [], "Kunne ikke hente HTML fra SelfService"

    if not all("Arbejdskalender" in html for html in html_pages):
        return [], "Siden loadede ikke korrekt - ikke på arbejdskalender siden"
    today = date.today()
    events = parse_selfservice_calendar_pages(html_pages, today, today + timedelta(days=days_ahead))
    if not events:
        return [], "Ingen vagter fundet i kalenderen - muligvis ingen vagter planlagt"
    return events, f"Synkronisering gennemført - {len(events)} vagter hentet"


def fetch_selfservice_schedule_from_authenticated_page(
    page: Any,
    days_ahead: int,
    driver_id: str,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch the first schedule in the interactive context that completed login."""
    paths = get_driver_paths(driver_id)
    settings = load_settings(driver_id)
    html_pages: list[str] = []

    try:
        open_selfservice_calendar(page, settings["url"])
        today_month = date.today().replace(day=1)
        navigate_selfservice_month(page, today_month.year, today_month.month)

        html = read_stable_page_content(page)
        if html is None:
            return [], "SelfService navigerer stadig. Prøv synkroniseringen igen om et øjeblik."
        html_pages.append(html)

        window_end = date.today() + timedelta(days=days_ahead)
        current_month = today_month
        final_month = window_end.replace(day=1)
        while current_month < final_month:
            if current_month.month == 12:
                current_month = current_month.replace(year=current_month.year + 1, month=1)
            else:
                current_month = current_month.replace(month=current_month.month + 1)
            navigate_selfservice_month(page, current_month.year, current_month.month)
            month_html = read_stable_page_content(page)
            if month_html is None:
                return [], f"Kunne ikke hente {current_month:%m/%Y} fra SelfService"
            html_pages.append(month_html)

        debug_path = paths["output_dir"] / "debug_html.log"
        debug_path.write_text(
            "\n<!-- ROSTERMATE MONTH BREAK -->\n".join(html_pages)[:300000],
            encoding="utf-8",
        )
    except Exception as exc:
        return [], f"SelfService-kalenderen kunne ikke åbnes: {exc}"

    if not all("Arbejdskalender" in html for html in html_pages):
        return [], "Siden loadede ikke korrekt - ikke på arbejdskalender siden"
    today = date.today()
    events = parse_selfservice_calendar_pages(
        html_pages,
        today,
        today + timedelta(days=days_ahead),
    )
    if not events:
        return [], "Ingen vagter fundet i kalenderen - muligvis ingen vagter planlagt"
    return events, f"Synkronisering gennemført - {len(events)} vagter hentet"


def run_interactive_initial_sync(
    page: Any,
    driver_id: str,
    settings: dict[str, Any],
    paths: dict[str, Path],
    history_prefix: str = "First run sync",
) -> dict[str, Any]:
    sync_lock = driver_sync_lock(driver_id)
    if not sync_lock.acquire(blocking=False):
        raise RuntimeError("En synkronisering kører allerede. Prøv igen om et øjeblik.")
    try:
        fetched = fetch_selfservice_schedule_from_authenticated_page(
            page,
            int(settings.get("days_ahead", 30)),
            driver_id,
        )
        result = run_initial_sync(
            driver_id,
            settings,
            paths,
            lambda _days, _driver_id: fetched,
            sync_schedule,
            write_outputs,
            load_json,
            load_history,
            save_history,
            history_prefix,
        )
        save_driver_settings(driver_id, {**settings, "selfservice_session_verified": True})
    finally:
        sync_lock.release()
    return {
        "sync_complete": True,
        "preview": result["preview"],
        "count": result["count"],
        "events": len(result["events"]),
        "message": result["message"],
    }


def run_automatic_sync_cycle(now: datetime | None = None) -> list[dict[str, str]]:
    """Run each due profile at most once in its current randomized time window."""
    current = now or datetime.now()
    outcomes: list[dict[str, str]] = []
    for driver_id in list_driver_ids():
        paths = get_driver_paths(driver_id)
        settings = load_settings(driver_id)
        session_store = SelfServiceSessionStore.from_paths(driver_id, paths)
        if not settings.get("wizard_completed"):
            continue
        if not session_store.has_saved_session() and not (settings.get("user") and settings.get("pass")):
            continue
        slot = automatic_sync_slot(settings, current)
        if slot is None:
            continue
        sync_lock = driver_sync_lock(driver_id)
        if not sync_lock.acquire(blocking=False):
            continue
        try:
            settings = load_settings(driver_id)
            slot = automatic_sync_slot(settings, current)
            if slot is None:
                continue
            attempted_settings = {**settings, LAST_ATTEMPT_KEY: slot}
            save_driver_settings(driver_id, attempted_settings)
            try:
                result = run_initial_sync(
                    driver_id,
                    attempted_settings,
                    paths,
                    fetch_schedule_with_retry,
                    sync_schedule,
                    write_outputs,
                    load_json,
                    load_history,
                    save_history,
                    "Automatisk sync",
                )
            except Exception as exc:
                history = load_history(paths["history_path"])
                history.append({
                    "timestamp": current.isoformat(),
                    "summary": f"Automatisk synkronisering fejlede: {exc}",
                    "changes": [],
                })
                save_history(history, paths["history_path"])
                outcomes.append({"driver_id": driver_id, "status": "error", "slot": slot})
            else:
                save_driver_settings(driver_id, {**attempted_settings, "selfservice_session_verified": True})
                outcomes.append({
                    "driver_id": driver_id,
                    "status": "synced",
                    "slot": slot,
                    "message": str(result.get("message", "")),
                })
        finally:
            sync_lock.release()
    return outcomes


def automatic_sync_worker(stop_event: threading.Event, interval_seconds: int = 30) -> None:
    while not stop_event.is_set():
        try:
            run_automatic_sync_cycle()
        except Exception as exc:
            print(f"[RosterMate automatic sync] {exc}", file=sys.stderr, flush=True)
        stop_event.wait(interval_seconds)


_AUTOMATIC_SYNC_THREAD: threading.Thread | None = None
_AUTOMATIC_SYNC_STOP = threading.Event()


def start_automatic_sync_worker() -> threading.Thread:
    global _AUTOMATIC_SYNC_THREAD
    if _AUTOMATIC_SYNC_THREAD is not None and _AUTOMATIC_SYNC_THREAD.is_alive():
        return _AUTOMATIC_SYNC_THREAD
    _AUTOMATIC_SYNC_STOP.clear()
    _AUTOMATIC_SYNC_THREAD = threading.Thread(
        target=automatic_sync_worker,
        args=(_AUTOMATIC_SYNC_STOP,),
        name="rostermate-automatic-sync",
        daemon=True,
    )
    _AUTOMATIC_SYNC_THREAD.start()
    return _AUTOMATIC_SYNC_THREAD


@app.route("/", methods=["GET", "POST"])
def home() -> Any:
    notice = ""
    driver_ids = list_driver_ids()
    if request.method == "GET" and len(driver_ids) == 1 and request.args.get("choose") != "1":
        only_driver_id = driver_ids[0]
        paths = get_driver_paths(only_driver_id)
        settings = load_settings(only_driver_id)
        session_store = SelfServiceSessionStore.from_paths(only_driver_id, paths)
        session["last_driver_id"] = only_driver_id
        has_existing_data = bool(
            load_json(paths["events_store_path"], [])
            or load_history(paths["history_path"])
        )
        if should_show_first_run(settings, session_store, has_existing_data=has_existing_data):
            return redirect(url_for("wizard_page", driver_id=only_driver_id))
        return redirect(url_for("index", driver_id=only_driver_id))

    if request.method == "POST":
        submitted_driver_id = request.form.get("driver_id", "")
        try:
            safe_driver_id = normalize_driver_id(submitted_driver_id)
        except ValueError:
            notice = "Indtast et gyldigt chaufførnummer med kun tal."
        else:
            session["last_driver_id"] = safe_driver_id
            paths = get_driver_paths(safe_driver_id)
            settings = load_settings(safe_driver_id)
            session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
            has_existing_data = bool(
                load_json(paths["events_store_path"], [])
                or load_history(paths["history_path"])
            )
            if should_show_first_run(settings, session_store, has_existing_data=has_existing_data):
                return redirect(url_for("wizard_page", driver_id=safe_driver_id))
            return redirect(url_for("index", driver_id=safe_driver_id))

    return render_template_string(
        """
        <!doctype html>
        <html lang="da">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>RosterMate</title>
            <style>
                :root {
                    --bg: #eef4fb;
                    --panel: #ffffff;
                    --text: #14213d;
                    --muted: #64748b;
                    --accent: #0f766e;
                    --border: #dbe6f2;
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    min-height: 100vh;
                    display: grid;
                    place-items: center;
                    padding: 1rem;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    color: var(--text);
                    background: radial-gradient(circle at top left, rgba(15, 118, 110, 0.14), transparent 28%), linear-gradient(180deg, #f7fbff 0%, var(--bg) 100%);
                }
                .panel {
                    width: min(100%, 520px);
                    background: var(--panel);
                    border: 1px solid var(--border);
                    border-radius: 28px;
                    padding: 1.5rem;
                    box-shadow: 0 24px 48px rgba(16, 33, 60, 0.12);
                }
                h1 { margin: 0 0 0.35rem; }
                p { color: var(--muted); }
                label { display: block; font-size: 0.92rem; color: var(--muted); margin-bottom: 0.35rem; }
                input {
                    width: 100%;
                    padding: 0.9rem 1rem;
                    border-radius: 14px;
                    border: 1px solid var(--border);
                    font: inherit;
                }
                button {
                    margin-top: 1rem;
                    width: 100%;
                    padding: 0.9rem 1rem;
                    border: none;
                    border-radius: 999px;
                    background: var(--accent);
                    color: white;
                    font: inherit;
                    font-weight: 700;
                    cursor: pointer;
                }
                .notice {
                    margin-top: 0.9rem;
                    padding: 0.85rem 1rem;
                    border-radius: 14px;
                    background: #fff4db;
                    color: #9a6700;
                    font-weight: 600;
                }
            </style>
        </head>
        <body>
            <form class="panel" method="post">
                <h1>{{ 'Tilføj profil' if driver_ids else 'Vælg chaufførnummer' }}</h1>
                <p>{{ 'Indtast chaufførnummeret til den ekstra profil.' if driver_ids else "RosterMate bruger chaufførnummer i URL'en, så flere ansatte kan dele samme maskine uden at blande data." }}</p>
                <label for="driver_id">Chaufførnummer</label>
                <input id="driver_id" name="driver_id" inputmode="numeric" pattern="[0-9]*" value="{{ last_driver_id }}" placeholder="Fx 1234" required>
                <button type="submit">Åbn dashboard</button>
                {% if notice %}
                <div class="notice">{{ notice }}</div>
                {% endif %}
            </form>
        </body>
        </html>
        """,
        last_driver_id=session.get("last_driver_id", ""),
        driver_ids=driver_ids,
        notice=notice,
    )


@app.route("/wizard/", methods=["GET", "POST"])
def global_wizard() -> Any:
    """Stable first-run address used by both platform installers."""
    return home()


@app.route("/<driver_id>/wizard")
def wizard_page(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    session["last_driver_id"] = safe_driver_id
    settings = load_settings(safe_driver_id)
    if not settings.get("calendar_access_token"):
        settings = {**settings, "calendar_access_token": secrets.token_urlsafe(24)}
        save_driver_settings(safe_driver_id, settings)
    history = load_history(paths["history_path"])
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    urls = driver_urls(safe_driver_id)
    force_relogin = request.args.get("relogin") == "1"
    welcome_back = should_show_welcome_back(settings, session_store) and not force_relogin

    if session_store.has_saved_session() and not settings.get("wizard_completed") and not force_relogin:
        return redirect(urls["wizard_preferences_url"])

    if not force_relogin and not should_show_first_run(
        settings,
        session_store,
        has_existing_data=bool(history),
    ) and not welcome_back:
        return redirect(urls["dashboard_url"])

    return render_template_string(
        FIRST_RUN_TEMPLATE,
        driver_id=safe_driver_id,
        urls=urls,
        welcome_back=welcome_back,
        version=APP_VERSION,
        last_sync=format_timestamp(history[-1].get("timestamp") if history else None),
        selfservice_user=settings.get("user", ""),
        has_saved_password=bool(settings.get("pass")),
        has_existing_data=bool(history),
        platform_labels=ui_platform_labels(),
    )


@app.route("/<driver_id>/wizard/connect", methods=["POST"])
def wizard_connect(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    if request.args.get("reset") == "1":
        login_manager.clear_driver_session(session_store)

    supplied_user = str(request.form.get("user", "")).strip()
    supplied_password = str(request.form.get("password", ""))
    if supplied_user:
        settings = {**settings, "user": supplied_user}
    if supplied_password:
        try:
            set_password(safe_driver_id, supplied_password)
            if get_password(safe_driver_id) != supplied_password:
                raise RuntimeError("adgangskoden kunne ikke læses tilbage efter lagring")
        except Exception as exc:
            return jsonify({
                "status": "error",
                "message": f"Adgangskoden kunne ikke gemmes i operativsystemets sikre nøglelager: {exc}",
            }), 500
        settings = {**settings, "pass": supplied_password}
    if supplied_user or supplied_password:
        save_driver_settings(safe_driver_id, settings)
        settings = load_settings(safe_driver_id)

    if request.args.get("interactive") != "1" and settings.get("user") and settings.get("pass"):
        login_manager.clear_driver_session(session_store)
        flow = login_manager.start_background(safe_driver_id)
        return jsonify({"status": "ok", "flow_id": flow.flow_id, "message": flow.message}), 200

    flow = login_manager.start(
        safe_driver_id,
        settings["url"],
        session_store,
        initial_sync=lambda page: run_interactive_initial_sync(
            page,
            safe_driver_id,
            settings,
            paths,
        ),
        credentials=(str(settings.get("user", "")), str(settings.get("pass", ""))),
    )
    return jsonify({"status": "ok", "flow_id": flow.flow_id, "message": flow.message}), 200


@app.route("/<driver_id>/wizard/status")
def wizard_status(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    flow_id = request.args.get("flow_id", "")
    flow = login_manager.get(flow_id)
    if flow is None or flow.driver_id != safe_driver_id:
        return jsonify({"status": "error", "state": "error", "message": "Ukendt wizard-flow"}), 404

    if flow.state == "connected" and not flow.payload.get("sync_complete"):
        sync_lock = driver_sync_lock(safe_driver_id)
        if not sync_lock.acquire(blocking=False):
            return jsonify({
                "status": "ok",
                "state": "syncing",
                "message": "Synkroniseringen fortsætter i baggrunden…",
            }), 200
        login_manager.update(flow_id, state="syncing", message="⟳ Synkroniserer…")
        try:
            settings = load_settings(safe_driver_id)
            initial_fetch = flow.payload.get("initial_fetch")
            fetcher = (
                (lambda _days, _driver_id: initial_fetch)
                if isinstance(initial_fetch, tuple) and len(initial_fetch) == 2
                else fetch_schedule_with_retry
            )
            result = run_initial_sync(
                safe_driver_id,
                settings,
                paths,
                fetcher,
                sync_schedule,
                write_outputs,
                load_json,
                load_history,
                save_history,
            )
        except Exception as exc:
            save_driver_settings(safe_driver_id, {**settings, "selfservice_session_verified": False})
            flow = login_manager.update(flow_id, state="error", message=str(exc))
        else:
            save_driver_settings(safe_driver_id, {**settings, "selfservice_session_verified": True})
            flow = login_manager.update(
                flow_id,
                state="synced",
                message=result["message"],
                payload={
                    "sync_complete": True,
                    "preview": result["preview"],
                    "count": result["count"],
                    "events": len(result["events"]),
                },
            )
        finally:
            sync_lock.release()

    current = login_manager.get(flow_id)
    if current is None:
        return jsonify({"status": "error", "state": "error", "message": "Wizard-flowet forsvandt"}), 404

    return jsonify(
        {
            "status": "ok",
            "state": current.state,
            "message": current.message,
            "preview": current.payload.get("preview", []),
            "count": current.payload.get("count", 0),
        }
    ), 200


@app.route("/<driver_id>/wizard/test-connection", methods=["POST"])
def wizard_test_connection(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    ok, message = login_manager.validate_saved_session(settings["url"], session_store)
    if ok:
        return jsonify({"status": "ok", "message": message}), 200
    return jsonify({"status": "error", "message": message}), 400


@app.route("/<driver_id>/wizard/preferences")
def wizard_preferences(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    if not session_store.has_saved_session():
        return redirect(url_for("wizard_page", driver_id=safe_driver_id))

    preview = build_sync_preview(load_json(paths["events_store_path"], []))
    return render_template_string(
        WIZARD_PREFERENCES_TEMPLATE,
        settings=with_setup_defaults(settings),
        preview=preview,
        preview_count=len(load_json(paths["events_store_path"], [])),
        urls=driver_urls(safe_driver_id),
        platform_labels=ui_platform_labels(),
    )


@app.route("/<driver_id>/wizard/complete", methods=["POST"])
def wizard_complete(driver_id: str) -> Any:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    updated_settings = apply_wizard_preferences(settings, request.form)
    save_driver_settings(safe_driver_id, updated_settings)
    sync_launch_agent_preference(
        safe_driver_id,
        bool(updated_settings.get("launch_at_login", False)),
        BASE_DIR,
        paths["output_dir"],
        reload_agent=False,
    )
    return redirect(driver_urls(safe_driver_id)["dashboard_url"])


@app.route("/<driver_id>/")
def index(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    session["last_driver_id"] = safe_driver_id
    settings = load_settings(safe_driver_id)
    if not settings.get("calendar_access_token"):
        settings = {**settings, "calendar_access_token": secrets.token_urlsafe(24)}
        save_driver_settings(safe_driver_id, settings)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    has_existing_data = bool(
        load_json(paths["events_store_path"], [])
        or load_history(paths["history_path"])
    )
    if should_show_first_run(settings, session_store, has_existing_data=has_existing_data):
        return redirect(url_for("wizard_page", driver_id=safe_driver_id))
    events = load_json(paths["events_store_path"], [])
    changes = load_json(paths["changes_path"], [])
    history = load_history(paths["history_path"])
    last_sync = format_timestamp(history[-1].get("timestamp") if history else None)
    next_events = select_next_calendar_events(events)
    upcoming_shifts = build_upcoming_shift_cards(next_events, date.today(), date.max)
    dashboard_changes = [describe_change(change) for change in changes[:5]]
    history_count = len(history)
    ics_ready = paths["ics_path"].exists() and paths["ics_path"].stat().st_size > 0
    urls = driver_urls(safe_driver_id)
    local_calendar_url = f"http://127.0.0.1:{application_port()}{urls['calendar_url']}"
    lan_calendar_url = calendar_subscription_address(
        safe_driver_id,
        str(settings["calendar_access_token"]),
    )
    public_calendar_base_url = str(settings.get("calendar_public_base_url") or "")
    public_calendar_url = (
        calendar_subscription_address(safe_driver_id, str(settings["calendar_access_token"]), public_calendar_base_url)
        if public_calendar_base_url
        else ""
    )
    needs_selfservice_setup = (
        not session_store.has_saved_session()
        or not settings.get("selfservice_session_verified")
    )
    show_profile_switcher = len(list_driver_ids()) > 1
    app_port = application_port()
    update_status = check_for_release_update(STORAGE_ROOT / "release_update.json", APP_VERSION)

    return render_template_string(
        """
        <!doctype html>
        <html lang="da">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>RosterMate Dashboard</title>
            <style>
                :root {
                    --bg: #eef4fb;
                    --panel: #ffffff;
                    --panel-2: #f5f9ff;
                    --text: #14213d;
                    --muted: #64748b;
                    --accent: #0f766e;
                    --accent-strong: #115e59;
                    --accent-2: #10213c;
                    --border: #dbe6f2;
                    --shadow: 0 18px 40px rgba(16, 33, 60, 0.08);
                    --success-bg: #e8f7ef;
                    --success-text: #166534;
                    --warning-bg: #fff4db;
                    --warning-text: #9a6700;
                    --danger-bg: #fce9e7;
                    --danger-text: #b42318;
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background:
                        radial-gradient(circle at top left, rgba(15, 118, 110, 0.14), transparent 28%),
                        linear-gradient(180deg, #f7fbff 0%, var(--bg) 100%);
                    color: var(--text);
                }
                a { color: inherit; text-decoration: none; }
                .container { max-width: 1180px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
                .topbar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 1rem;
                    margin-bottom: 1rem;
                }
                .brand {
                    display: flex;
                    align-items: center;
                    gap: 0.85rem;
                    font-weight: 700;
                }
                .brand img {
                    width: 42px;
                    height: 42px;
                    border-radius: 12px;
                    background: white;
                    padding: 0.2rem;
                    box-shadow: 0 8px 20px rgba(16, 33, 60, 0.12);
                }
                .nav {
                    display: flex;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                }
                .topbar-actions {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    flex-wrap: wrap;
                }
                .nav a {
                    padding: 0.7rem 1rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(219, 230, 242, 0.9);
                    color: var(--accent-2);
                    font-weight: 600;
                    backdrop-filter: blur(10px);
                }
                .nav a.active {
                    background: var(--accent-2);
                    color: white;
                    border-color: var(--accent-2);
                }
                .update-banner {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 1rem;
                    padding: 1rem 1.15rem;
                    border: 1px solid #f3cf74;
                    border-radius: 18px;
                    background: var(--warning-bg);
                    color: var(--warning-text);
                    box-shadow: var(--shadow);
                }
                .update-banner-copy {
                    display: grid;
                    gap: 0.2rem;
                }
                .update-banner .button-link {
                    flex: 0 0 auto;
                    background: var(--warning-text);
                    color: white;
                    border-color: var(--warning-text);
                }
                .profile-switcher {
                    display: flex;
                    align-items: center;
                    gap: 0.55rem;
                    padding: 0.45rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(219, 230, 242, 0.9);
                    backdrop-filter: blur(10px);
                }
                .profile-switcher input {
                    width: 112px;
                    padding: 0.6rem 0.8rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    background: white;
                    font: inherit;
                }
                .profile-switcher button {
                    width: auto;
                    margin-top: 0;
                    padding: 0.65rem 0.95rem;
                }
                .setup-banner {
                    margin-top: 1rem;
                    padding: 0.95rem 1rem;
                    border-radius: 18px;
                    background: rgba(255, 244, 219, 0.18);
                    border: 1px solid rgba(255, 244, 219, 0.22);
                }
                .setup-banner strong {
                    display: block;
                    margin-bottom: 0.25rem;
                }
                .hero {
                    background:
                        linear-gradient(135deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.02)),
                        linear-gradient(120deg, var(--accent-2) 0%, #17355f 56%, #0f766e 100%);
                    color: white;
                    border-radius: 28px;
                    padding: 1.6rem;
                    margin-bottom: 1rem;
                    box-shadow: 0 24px 48px rgba(16, 33, 60, 0.18);
                }
                .hero-shell {
                    display: grid;
                    grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.9fr);
                    gap: 1.2rem;
                    align-items: stretch;
                }
                .hero-copy h1 { margin: 0 0 0.35rem; font-size: 2rem; }
                .hero-copy p { margin: 0; opacity: 0.88; max-width: 56ch; }
                .hero-meta {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.75rem;
                    margin-top: 1rem;
                }
                .hero-chip {
                    padding: 0.75rem 0.9rem;
                    border-radius: 18px;
                    background: rgba(255, 255, 255, 0.12);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    min-width: 150px;
                }
                .hero-chip strong, .hero-side strong {
                    display: block;
                    font-size: 0.8rem;
                    text-transform: uppercase;
                    letter-spacing: 0.05em;
                    opacity: 0.75;
                    margin-bottom: 0.35rem;
                }
                .hero-chip span, .hero-side span {
                    font-size: 1rem;
                    font-weight: 700;
                }
                .hero-side {
                    background: rgba(255, 255, 255, 0.08);
                    border-radius: 22px;
                    padding: 1.1rem;
                    border: 1px solid rgba(255, 255, 255, 0.12);
                }
                .hero-side p {
                    margin: 0.2rem 0 1rem;
                    opacity: 0.84;
                }
                .hero-actions {
                    display: flex;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                    margin-top: 1rem;
                }
                .grid { display: grid; gap: 1rem; }
                .summary-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 1rem; }
                .content-grid { grid-template-columns: minmax(0, 1.55fr) minmax(320px, 1fr); }
                .card {
                    background: var(--panel);
                    border: 1px solid var(--border);
                    border-radius: 22px;
                    padding: 1.2rem;
                    box-shadow: var(--shadow);
                }
                .card h2 { margin: 0 0 0.35rem; font-size: 1.05rem; }
                .card-head {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    gap: 1rem;
                    margin-bottom: 0.85rem;
                }
                .stat { font-size: 1.8rem; font-weight: 700; margin: 0.2rem 0; }
                .muted { color: var(--muted); }
                .pill { display: inline-block; padding: 0.28rem 0.65rem; border-radius: 999px; background: #dff4f1; color: var(--accent-strong); font-size: 0.8rem; font-weight: 700; }
                button, select, input { font: inherit; }
                button {
                    background: var(--accent);
                    color: white;
                    border: none;
                    border-radius: 999px;
                    padding: 0.8rem 1.1rem;
                    cursor: pointer;
                    font-weight: 600;
                }
                button.secondary, .button-link.secondary {
                    background: transparent;
                    color: white;
                    border: 1px solid rgba(255, 255, 255, 0.22);
                }
                .button-link {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    border-radius: 999px;
                    padding: 0.8rem 1.1rem;
                    font-weight: 600;
                }
                .button-link.ghost {
                    color: var(--accent-2);
                    border: 1px solid var(--border);
                    background: var(--panel-2);
                }
                .small { font-size: 0.9rem; color: var(--muted); }
                .row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
                .field { display: block; margin-top: 0.6rem; }
                .field select, .field input {
                    margin-top: 0.25rem;
                    width: 100%;
                    padding: 0.75rem 0.85rem;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    background: white;
                }
                .field label { font-size: 0.9rem; color: var(--muted); }
                .summary-card {
                    display: flex;
                    flex-direction: column;
                    gap: 0.35rem;
                    justify-content: space-between;
                    min-height: 132px;
                }
                .shift-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 0.9rem;
                }
                .shift-card {
                    padding: 1rem;
                    border-radius: 20px;
                    background: linear-gradient(180deg, #f8fbff 0%, #eff7ff 100%);
                    border: 1px solid var(--border);
                    display: grid;
                    gap: 0.85rem;
                }
                .shift-card.today {
                    border-color: rgba(15, 118, 110, 0.35);
                    box-shadow: 0 10px 30px rgba(15, 118, 110, 0.12);
                }
                .shift-card.empty {
                    align-content: center;
                    min-height: 180px;
                }
                .shift-date {
                    font-size: 0.82rem;
                    font-weight: 700;
                    letter-spacing: 0.04em;
                    color: var(--accent-strong);
                    text-transform: uppercase;
                    margin-bottom: 0.15rem;
                }
                .shift-day-head {
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    gap: 0.75rem;
                }
                .shift-day-head strong {
                    display: block;
                    font-size: 1rem;
                }
                .day-marker {
                    padding: 0.3rem 0.6rem;
                    border-radius: 999px;
                    background: #dff4f1;
                    color: var(--accent-strong);
                    font-size: 0.78rem;
                    font-weight: 700;
                    white-space: nowrap;
                }
                .day-shifts {
                    display: grid;
                    gap: 0.6rem;
                }
                .shift-entry {
                    display: grid;
                    grid-template-columns: 38px minmax(0, 1fr);
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.7rem 0.75rem;
                    border-radius: 16px;
                    background: rgba(255, 255, 255, 0.78);
                    border: 1px solid rgba(219, 230, 242, 0.9);
                }
                .shift-entry.all-day {
                    background: #fff9eb;
                }
                .shift-icon {
                    width: 38px;
                    height: 38px;
                    border-radius: 12px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 0.9rem;
                    font-weight: 800;
                    color: var(--accent-2);
                    background: #e4eefb;
                }
                .type-work .shift-icon {
                    background: #dbeafe;
                    color: #1d4ed8;
                }
                .type-off .shift-icon {
                    background: #e8f7ef;
                    color: #166534;
                }
                .type-vacation .shift-icon {
                    background: #fff4db;
                    color: #9a6700;
                }
                .shift-entry-top {
                    display: flex;
                    justify-content: space-between;
                    gap: 0.65rem;
                    align-items: center;
                    margin-bottom: 0.2rem;
                }
                .shift-entry-top strong {
                    display: block;
                    font-size: 0.95rem;
                }
                .shift-type {
                    padding: 0.2rem 0.5rem;
                    border-radius: 999px;
                    font-size: 0.75rem;
                    font-weight: 700;
                    white-space: nowrap;
                }
                .type-work .shift-type {
                    background: #dbeafe;
                    color: #1d4ed8;
                }
                .type-off .shift-type {
                    background: #e8f7ef;
                    color: #166534;
                }
                .type-vacation .shift-type {
                    background: #fff4db;
                    color: #9a6700;
                }
                .shift-time {
                    color: var(--muted);
                    font-size: 0.9rem;
                }
                .stack {
                    display: grid;
                    gap: 1rem;
                }
                .change-list {
                    list-style: none;
                    padding: 0;
                    margin: 0;
                    display: grid;
                    gap: 0.8rem;
                }
                .change-item {
                    border: 1px solid var(--border);
                    border-radius: 18px;
                    padding: 0.9rem 1rem;
                    background: #fbfdff;
                }
                .change-top {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.8rem;
                    margin-bottom: 0.35rem;
                }
                .badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 0.28rem 0.65rem;
                    border-radius: 999px;
                    font-size: 0.78rem;
                    font-weight: 700;
                }
                .badge-added { background: var(--success-bg); color: var(--success-text); }
                .badge-removed { background: var(--danger-bg); color: var(--danger-text); }
                .badge-changed { background: var(--warning-bg); color: var(--warning-text); }
                .quick-actions {
                    display: grid;
                    gap: 0.75rem;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                }
                .quick-card {
                    padding: 1rem;
                    border-radius: 18px;
                    border: 1px solid var(--border);
                    background: var(--panel-2);
                }
                .quick-card strong {
                    display: block;
                    margin-bottom: 0.3rem;
                }
                .section-link {
                    color: var(--accent-strong);
                    font-weight: 700;
                }
                .week-nav {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    margin-bottom: 1rem;
                    padding: 0.85rem 1rem;
                    border-radius: 18px;
                    background: var(--panel-2);
                    border: 1px solid var(--border);
                }
                .week-nav strong {
                    display: block;
                    font-size: 1rem;
                }
                .week-nav-links {
                    display: flex;
                    gap: 0.6rem;
                    flex-wrap: wrap;
                }
                .week-link {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 0.65rem 0.95rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    background: white;
                    font-weight: 700;
                    color: var(--accent-2);
                }
                .week-link.current {
                    background: #dff4f1;
                    color: var(--accent-strong);
                    border-color: rgba(15, 118, 110, 0.2);
                }
                @media (max-width: 980px) {
                    .hero-shell,
                    .summary-grid,
                    .content-grid {
                        grid-template-columns: 1fr;
                    }
                }
                @media (max-width: 700px) {
                    .container {
                        padding: 1rem 0.9rem 2rem;
                    }
                    .topbar {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .topbar-actions {
                        width: 100%;
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .nav {
                        width: 100%;
                    }
                    .nav a {
                        flex: 1 1 140px;
                        text-align: center;
                    }
                    .hero {
                        padding: 1.15rem;
                    }
                    .hero-copy h1 {
                        font-size: 1.6rem;
                    }
                    .profile-switcher {
                        width: 100%;
                    }
                    .profile-switcher input,
                    .profile-switcher button {
                        width: 100%;
                    }
                    .hero-actions,
                    .row,
                    .week-nav {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .hero-actions > *,
                    .row > *,
                    .week-nav-links,
                    .week-nav-links > * {
                        width: 100%;
                    }
                    button,
                    .button-link {
                        width: 100%;
                    }
                }
            </style>
            <script>
                function showNotification(message, type = 'success') {
                    const notif = document.getElementById('notification');
                    const text = document.getElementById('notification-text');
                    text.textContent = message;
                    notif.style.background = type === 'error' ? '#ef4444' : '#10b981';
                    notif.style.display = 'block';
                    notif.title = type === 'error' ? 'Klik for at lukke' : '';
                    notif.onclick = type === 'error' ? () => { notif.style.display = 'none'; } : null;
                    if (type !== 'error') {
                        setTimeout(() => {
                            notif.style.display = 'none';
                            setTimeout(() => location.reload(), 1000);
                        }, 3000);
                    }
                }

                function handleFormSubmit(e, endpoint) {
                    e.preventDefault();
                    const form = e.target;
                    const formData = new FormData(form);

                    fetch(endpoint, {
                        method: 'POST',
                        body: formData
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.status === 'ok' && data.flow_id && data.status_url) {
                            showNotification(data.message || 'SelfService-login åbnes…', 'success');
                            pollInteractiveSync(data.status_url);
                        } else if (data.status === 'ok') {
                            showNotification(data.message || 'Færdig', 'success');
                        } else {
                            showNotification(data.message || 'Fejl', 'error');
                        }
                    })
                    .catch(err => showNotification('Netværksfejl: ' + err.message, 'error'));
                }

                function pollInteractiveSync(statusUrl) {
                    const poll = () => {
                        fetch(statusUrl)
                            .then(r => r.json())
                            .then(data => {
                                if (data.state === 'synced') {
                                    showNotification(data.message || 'Synkronisering gennemført', 'success');
                                    return;
                                }
                                if (data.state === 'error') {
                                    showNotification(data.message || 'Synkroniseringen fejlede', 'error');
                                    return;
                                }
                                setTimeout(poll, 1000);
                            })
                            .catch(err => showNotification('Netværksfejl: ' + err.message, 'error'));
                    };
                    poll();
                }
            </script>
        </head>
        <body>
            <div id="notification" style="display:none; position:fixed; top:20px; right:20px; background:#10b981; color:white; padding:1rem 1.5rem; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.2); z-index:9999; max-width:400px; font-weight:600;">
                <span id="notification-text"></span>
            </div>
            <div class="container">
                <div class="topbar">
                    <div class="brand">
                        <img src="/static/Rostermate.png" alt="RosterMate logo">
                        <span>RosterMate · {{ driver_id }}</span>
                    </div>
                    <div class="topbar-actions">
                        <nav class="nav" aria-label="Hovednavigation">
                            <a href="{{ urls.dashboard_url }}" class="active">Dashboard</a>
                            <a href="{{ urls.settings_url }}">Indstillinger</a>
                            <a href="{{ urls.history_url }}">Historik</a>
                            {% if not show_profile_switcher %}<a href="/?choose=1">Tilføj profil</a>{% endif %}
                        </nav>
                        {% if show_profile_switcher %}
                        <form class="profile-switcher" action="/" method="post">
                            <input name="driver_id" inputmode="numeric" pattern="[0-9]*" value="{{ driver_id }}" aria-label="Skift chaufførnummer">
                            <button type="submit">Skift profil</button>
                        </form>
                        {% endif %}
                    </div>
                </div>
                {% if update_status.available and update_status.download_url %}
                <div class="update-banner" role="status">
                    <div class="update-banner-copy">
                        <strong>Ny RosterMate-version er tilgængelig</strong>
                        <span>Version {{ update_status.latest_version }} kan hentes til {{ 'Windows' if update_status.platform == 'win32' else 'macOS' }}.</span>
                    </div>
                    <a class="button-link" href="{{ update_status.download_url }}" target="_blank" rel="noopener noreferrer">Hent opdatering</a>
                </div>
                {% endif %}
                <div class="hero">
                    <div class="hero-shell">
                        <div class="hero-copy">
                            <span class="pill">Driftsoversigt</span>
                            <h1>Se næste vagter hurtigere og hold sync under kontrol.</h1>
                            <p>Forsiden fokuserer nu på det daglige workflow: status, næste synkronisering, kommende vagter og de seneste ændringer.</p>
                            <div class="hero-meta">
                                <div class="hero-chip">
                                    <strong>Status</strong>
                                    <span>{{ status }}</span>
                                </div>
                                <div class="hero-chip">
                                    <strong>Sidste sync</strong>
                                    <span>{{ last_sync }}</span>
                                </div>
                                <div class="hero-chip">
                                    <strong>Næste sync</strong>
                                    <span>{{ next_sync }}</span>
                                </div>
                            </div>
                            {% if needs_selfservice_setup %}
                            <div class="setup-banner">
                                <strong>Første opsætning mangler</strong>
                                <span>Tilføj dit SelfService-login i indstillinger, før første synkronisering kan hente vagter.</span>
                            </div>
                            {% endif %}
                        </div>
                        <div class="hero-side">
                            <strong>Hovedhandling</strong>
                            <span>Synkronisér de næste {{ days_ahead }} dage</span>
                            <p>Brug sync her og flyt konfiguration til indstillingssiden, så dashboardet forbliver enkelt.</p>
                            <form onsubmit="handleFormSubmit(event, '{{ urls.sync_url }}')">
                                <div class="field">
                                    <label for="days_ahead">Dage frem</label>
                                    <select name="days_ahead" id="days_ahead">
                                        {% for value in range(1, 31) %}
                                        <option value="{{ value }}" {% if value == days_ahead %}selected{% endif %}>{{ value }}</option>
                                        {% endfor %}
                                    </select>
                                </div>
                                <div class="hero-actions">
                                    <button type="submit">Synk nu</button>
                                    {% if needs_selfservice_setup %}
                                    <a class="button-link secondary" href="{{ urls.wizard_relogin_url }}">Forbind SelfService</a>
                                    {% else %}
                                    <a class="button-link secondary" href="{{ urls.settings_url }}">Åbn indstillinger</a>
                                    {% endif %}
                                </div>
                            </form>
                        </div>
                    </div>
                </div>
                <div class="grid summary-grid">
                    <div class="card summary-card">
                        <span class="pill">Ansættelse</span>
                        <div>
                            <p class="stat">{{ employment_type_display }}</p>
                            <p class="muted">{{ employment_type_label }}</p>
                        </div>
                    </div>
                    <div class="card summary-card">
                        <span class="pill">Kalenderposter</span>
                        <div>
                            <p class="stat">{{ event_count }}</p>
                            <p class="muted">Gemte poster i kalenderuddata</p>
                        </div>
                    </div>
                    <div class="card summary-card">
                        <span class="pill">Historik</span>
                        <div>
                            <p class="stat">{{ history_count }}</p>
                            <p class="muted">Gemte handlinger i loggen</p>
                        </div>
                    </div>
                    <div class="card summary-card">
                        <span class="pill">Kalenderfil</span>
                        <div>
                            <p class="stat">{{ 'Klar' if ics_ready else 'Mangler' }}</p>
                            <p class="muted">ICS eksport til kalenderapps</p>
                        </div>
                    </div>
                </div>
                <div class="grid content-grid">
                    <div class="card">
                        <div class="card-head">
                            <div>
                                <h2>De næste 7 kalenderdage</h2>
                                <p class="small">Kun kommende poster fra i dag, sorteret efter dato og starttid.</p>
                            </div>
                            <a class="section-link" href="{{ urls.history_url }}">Se historik</a>
                        </div>
                        <div class="shift-grid">
                            {% for day in upcoming_shifts %}
                            <article class="shift-card{% if day.is_today %} today{% endif %}">
                                <div class="shift-day-head">
                                    <div>
                                        <div class="shift-date">{{ day.date_label }}</div>
                                        <strong>{{ day.weekday }}</strong>
                                    </div>
                                    {% if day.is_today %}
                                    <span class="day-marker">I dag</span>
                                    {% endif %}
                                </div>
                                <div class="day-shifts">
                                    {% for shift in day.shifts %}
                                    <div class="shift-entry {{ shift.type_class }} {{ shift.variant }}">
                                        <span class="shift-icon">{{ shift.icon }}</span>
                                        <div>
                                            <div class="shift-entry-top">
                                                <strong>{{ shift.title }}</strong>
                                                <span class="shift-type">{{ shift.type_label }}</span>
                                            </div>
                                            <div class="shift-time">{{ shift.time_label }}</div>
                                        </div>
                                    </div>
                                    {% endfor %}
                                </div>
                            </article>
                            {% else %}
                            <article class="shift-card empty">
                                <strong>Ingen vagter endnu</strong>
                                <div class="small">Kør en synkronisering for at hente de første kalenderposter.</div>
                            </article>
                            {% endfor %}
                        </div>
                    </div>
                    <div class="stack">
                        <div class="card">
                            <div class="card-head">
                                <div>
                                    <h2>Seneste ændringer</h2>
                                    <p class="small">Viser de nyeste registrerede forskelle i planen.</p>
                                </div>
                                <a class="section-link" href="{{ urls.history_url }}">Fuld historik</a>
                            </div>
                            <ul class="change-list">
                                {% for change in dashboard_changes %}
                                <li class="change-item">
                                    <div class="change-top">
                                        <span class="badge {{ change.badge_class }}">{{ change.badge_text }}</span>
                                        <span class="small">{{ change.date_label }}</span>
                                    </div>
                                    <strong>{{ change.title }}</strong>
                                    <div class="small">{{ change.detail or 'Ingen ekstra detaljer' }}</div>
                                </li>
                                {% else %}
                                <li class="change-item">
                                    <strong>Ingen ændringer endnu</strong>
                                    <div class="small">Når import eller sammenligning finder forskelle, vises de her.</div>
                                </li>
                                {% endfor %}
                            </ul>
                        </div>
                        <div class="card">
                            <div class="card-head">
                                <div>
                                    <h2>Hurtige handlinger</h2>
                                    <p class="small">Sekundære funktioner er flyttet væk fra forsiden, men stadig lette at finde.</p>
                                </div>
                            </div>
                            <div class="quick-actions">
                                <div class="quick-card">
                                    <strong>Indstillinger</strong>
                                    <div class="small">Redigér ansættelsesform, login og sync-præferencer.</div>
                                    <div style="margin-top:0.8rem;"><a class="button-link ghost" href="{{ urls.settings_url }}">Åbn</a></div>
                                </div>
                                <div class="quick-card">
                                    <strong>Historik</strong>
                                    <div class="small">Se tidligere importer og synkroniseringer samlet ét sted.</div>
                                    <div style="margin-top:0.8rem;"><a class="button-link ghost" href="{{ urls.history_url }}">Vis log</a></div>
                                </div>
                                <div class="quick-card">
                                    <strong>ICS eksport</strong>
                                    <div class="small">{{ 'Kalenderfilen er klar til brug.' if ics_ready else 'Kalenderfilen oprettes efter første sync.' }}</div>
                                    <div style="margin-top:0.8rem;"><a class="button-link ghost" href="{{ urls.calendar_url }}">Åbn fil</a></div>
                                    <div class="small" style="margin-top:0.7rem;"><strong>{{ platform_labels.local_device }}</strong></div>
                                    <div class="small" style="overflow-wrap:anywhere;">{{ local_calendar_url }}</div>
                                    <div class="small" style="margin-top:0.7rem;"><strong>Samme Wi-Fi</strong></div>
                                    <div class="small" style="overflow-wrap:anywhere;">{{ lan_calendar_url }}</div>
                                    {% if public_calendar_url %}
                                    <div class="small" style="margin-top:0.7rem;"><strong>Overalt via HTTPS</strong></div>
                                    <div class="small" style="overflow-wrap:anywhere;">{{ public_calendar_url }}</div>
                                    {% endif %}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="small" style="margin-top:1rem; text-align:center;">
                    RosterMate {{ software.version }} · commit {{ software.commit }} · software opdateret {{ software.updated_at }}
                </div>
            </div>
        </body>
        </html>
        """,
        driver_id=safe_driver_id,
        status="Klar til sync",
        last_sync=last_sync,
        next_sync=calculate_next_sync(settings),
        employment_type=settings["employment_type"],
        employment_type_label="Ansættelsesform",
        employment_type_display={
            "ramme_ansat": "Ramme ansat",
            "fast_turnus": "Fast turnus",
            "timeloennet": "Timelønnet",
        }.get(settings["employment_type"], "Ramme ansat"),
        days_ahead=settings["days_ahead"],
        remove_old_shifts=settings["remove_old_shifts"],
        event_count=len(events),
        upcoming_shifts=upcoming_shifts,
        dashboard_changes=dashboard_changes,
        history_count=history_count,
        ics_ready=ics_ready,
        urls=urls,
        local_calendar_url=local_calendar_url,
        lan_calendar_url=lan_calendar_url,
        public_calendar_url=public_calendar_url,
        software=software_info(),
        show_profile_switcher=show_profile_switcher,
        app_port=app_port,
        needs_selfservice_setup=needs_selfservice_setup,
        update_status=update_status,
        platform_labels=ui_platform_labels(),
    )


@app.route("/<driver_id>/import", methods=["POST"])
def import_plan(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    payload = request.form.get("plan_json", "[]")
    try:
        parsed_plan = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({"status": "error", "message": "Ugyldig JSON"}), 400

    if not isinstance(parsed_plan, list):
        return jsonify({"status": "error", "message": "Planen skal være en liste"}), 400

    old_plan = load_plan(paths["plan_path"])
    changes = compare_plans(old_plan, parsed_plan)
    save_plan(parsed_plan, paths["plan_path"])

    history = load_history(paths["history_path"])
    history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "summary": f"Importerede {len(parsed_plan)} vagter",
            "changes": changes,
        }
    )
    save_history(history, paths["history_path"])

    return jsonify({"status": "ok", "message": "Plan importeret", "changes": changes})


@app.route("/<driver_id>/sync", methods=["POST"])
def sync_route(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    days_ahead = int(request.form.get("days_ahead", settings.get("days_ahead", 7)))
    updated_settings = {
        **settings,
        "days_ahead": days_ahead,
        "remove_old_shifts": request.form.get("remove_old_shifts") == "true",
    }
    save_driver_settings(safe_driver_id, updated_settings)
    sync_lock = driver_sync_lock(safe_driver_id)
    if not sync_lock.acquire(blocking=False):
        return jsonify({
            "status": "error",
            "message": "En synkronisering kører allerede. Prøv igen om et øjeblik.",
        }), 409
    try:
        saved_events, saved_status = fetch_selfservice_schedule(
            days_ahead,
            safe_driver_id,
            allow_credential_login=True,
            headless=True,
        )
        if saved_events:
            result = run_initial_sync(
                safe_driver_id,
                updated_settings,
                paths,
                lambda _days, _driver_id: (saved_events, saved_status),
                sync_schedule,
                write_outputs,
                load_json,
                load_history,
                save_history,
                "Synkronisering",
            )
            save_driver_settings(
                safe_driver_id,
                {**updated_settings, "selfservice_session_verified": True},
            )
            return jsonify({
                "status": "ok",
                "message": result["message"],
                "events": result["events"],
                "changes": result["changes"],
            }), 200
    finally:
        sync_lock.release()

    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    flow = login_manager.start(
        safe_driver_id,
        updated_settings["url"],
        session_store,
        initial_sync=lambda page: run_interactive_initial_sync(
            page,
            safe_driver_id,
            updated_settings,
            paths,
            "Synkronisering",
        ),
        credentials=(
            str(updated_settings.get("user", "")),
            str(updated_settings.get("pass", "")),
        ),
    )
    return jsonify({
        "status": "ok",
        "flow_id": flow.flow_id,
        "status_url": url_for("wizard_status", driver_id=safe_driver_id, flow_id=flow.flow_id),
        "message": "SelfService-login åbnes. Log ind, så henter RosterMate vagterne.",
    }), 200


@app.route("/<driver_id>/settings-page")
def settings_page(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    session["last_driver_id"] = safe_driver_id
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    notice = request.args.get("notice", "")
    notice_type = request.args.get("notice_type", "success")
    urls = driver_urls(safe_driver_id)
    has_selfservice_session = session_store.has_saved_session()
    needs_selfservice_setup = not has_selfservice_session
    show_profile_switcher = len(list_driver_ids()) > 1
    app_port = application_port()
    return render_template_string(
        """
        <!doctype html>
        <html lang="da">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>RosterMate Indstillinger</title>
            <style>
                :root {
                    --bg: #eef4fb;
                    --panel: #ffffff;
                    --panel-2: #f5f9ff;
                    --text: #14213d;
                    --muted: #64748b;
                    --accent: #0f766e;
                    --accent-2: #10213c;
                    --border: #dbe6f2;
                    --shadow: 0 18px 40px rgba(16, 33, 60, 0.08);
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    color: var(--text);
                    background: linear-gradient(180deg, #f7fbff 0%, var(--bg) 100%);
                }
                a { color: inherit; text-decoration: none; }
                .container { max-width: 980px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
                .topbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 1rem; }
                .nav { display: flex; gap: 0.7rem; flex-wrap: wrap; }
                .topbar-actions { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
                .nav a {
                    padding: 0.7rem 1rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.82);
                    border: 1px solid var(--border);
                    font-weight: 600;
                }
                .nav a.active { background: var(--accent-2); color: white; }
                .profile-switcher {
                    display: flex;
                    align-items: center;
                    gap: 0.55rem;
                    padding: 0.45rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.82);
                    border: 1px solid var(--border);
                }
                .profile-switcher input {
                    width: 112px;
                    padding: 0.65rem 0.8rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    font: inherit;
                }
                .profile-switcher button {
                    width: auto;
                    padding: 0.75rem 1rem;
                }
                .panel {
                    background: var(--panel);
                    border: 1px solid var(--border);
                    border-radius: 24px;
                    padding: 1.4rem;
                    box-shadow: var(--shadow);
                }
                .intro {
                    background: linear-gradient(120deg, var(--accent-2) 0%, #17355f 60%, #0f766e 100%);
                    color: white;
                    border-radius: 24px;
                    padding: 1.3rem;
                    margin-bottom: 1rem;
                }
                .intro h1 { margin: 0 0 0.35rem; }
                .intro p { margin: 0; opacity: 0.86; }
                .section-grid {
                    display: grid;
                    gap: 1rem;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
                .section {
                    padding: 1rem;
                    border-radius: 18px;
                    border: 1px solid var(--border);
                    background: var(--panel-2);
                }
                .section.setup-highlight {
                    background: linear-gradient(180deg, #fffdfa 0%, #fff4db 100%);
                    border-color: #f2d58a;
                }
                .connection-card {
                    margin-top: 1rem;
                    padding: 1rem;
                    border-radius: 18px;
                    background: rgba(255, 255, 255, 0.72);
                    border: 1px solid rgba(16, 33, 60, 0.08);
                }
                .connection-status {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.45rem 0.75rem;
                    border-radius: 999px;
                    font-size: 0.86rem;
                    font-weight: 700;
                }
                .connection-status.connected { background: #e8f7ef; color: #166534; }
                .connection-status.disconnected { background: #fff4db; color: #9a6700; }
                .inline-actions {
                    display: flex;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                    margin-top: 1rem;
                }
                .section.span-2 { grid-column: 1 / -1; }
                .section h2 { margin: 0 0 0.35rem; font-size: 1rem; }
                .small { color: var(--muted); font-size: 0.92rem; }
                .setup-shell {
                    display: grid;
                    grid-template-columns: minmax(0, 1.2fr) minmax(240px, 0.9fr);
                    gap: 1rem;
                    align-items: start;
                }
                .setup-steps {
                    display: grid;
                    gap: 0.75rem;
                }
                .setup-step {
                    display: grid;
                    grid-template-columns: 38px minmax(0, 1fr);
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.85rem 0.9rem;
                    border-radius: 16px;
                    border: 1px solid rgba(16, 33, 60, 0.08);
                    background: rgba(255, 255, 255, 0.68);
                }
                .setup-step-number {
                    width: 38px;
                    height: 38px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    border-radius: 12px;
                    background: #10213c;
                    color: white;
                    font-weight: 800;
                }
                .setup-tips {
                    padding: 1rem;
                    border-radius: 18px;
                    background: rgba(255, 255, 255, 0.76);
                    border: 1px solid rgba(16, 33, 60, 0.08);
                }
                .setup-tips ul {
                    margin: 0.75rem 0 0;
                    padding-left: 1rem;
                    color: var(--muted);
                }
                .field.password-field {
                    position: relative;
                }
                .field-hint {
                    margin-top: 0.35rem;
                    color: var(--muted);
                    font-size: 0.85rem;
                }
                .field { display: block; margin-top: 0.8rem; }
                .field label { display: block; margin-bottom: 0.35rem; color: var(--muted); font-size: 0.9rem; }
                .field input, .field select {
                    width: 100%;
                    padding: 0.78rem 0.85rem;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    background: white;
                    font: inherit;
                }
                .row { display: flex; gap: 0.6rem; align-items: center; margin-top: 1rem; }
                button {
                    background: var(--accent);
                    color: white;
                    border: none;
                    border-radius: 999px;
                    padding: 0.85rem 1.15rem;
                    font: inherit;
                    font-weight: 700;
                    cursor: pointer;
                }
                .helper-links {
                    display: flex;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                    margin-top: 1rem;
                }
                .helper-links a {
                    padding: 0.75rem 1rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    background: white;
                    font-weight: 600;
                }
                .notice {
                    padding: 0.9rem 1rem;
                    border-radius: 16px;
                    margin-bottom: 1rem;
                    font-weight: 600;
                }
                .notice.success { background: #e8f7ef; color: #166534; }
                .notice.error { background: #fce9e7; color: #b42318; }
                .notice.warning { background: #fff4db; color: #9a6700; }
                .ghost-button {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    padding: 0.85rem 1.15rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    background: white;
                    font: inherit;
                    font-weight: 700;
                    color: var(--accent-2);
                    cursor: pointer;
                }
                @media (max-width: 760px) {
                    .section-grid { grid-template-columns: 1fr; }
                    .topbar { flex-direction: column; align-items: stretch; }
                    .topbar-actions,
                    .setup-shell,
                    .profile-switcher {
                        grid-template-columns: 1fr;
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .helper-links {
                        flex-direction: column;
                    }
                    .profile-switcher input,
                    .profile-switcher button {
                        width: 100%;
                    }
                }
            </style>
            <script>
                function showNotification(message, type = 'success') {
                    const notif = document.getElementById('notification');
                    const text = document.getElementById('notification-text');
                    text.textContent = message;
                    notif.style.background = type === 'error' ? '#ef4444' : '#10b981';
                    notif.style.display = 'block';
                    notif.title = type === 'error' ? 'Klik for at lukke' : '';
                    notif.onclick = type === 'error' ? () => { notif.style.display = 'none'; } : null;
                    if (type !== 'error') {
                        setTimeout(() => {
                            notif.style.display = 'none';
                        }, 3000);
                    }
                }

                function handleSettingsSubmit(e) {
                    e.preventDefault();
                    const form = e.target;
                    const formData = new FormData(form);
                    fetch('{{ urls.settings_post_url }}', {
                        method: 'POST',
                        body: formData
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.status === 'ok') {
                            showNotification(data.message || 'Indstillinger gemt');
                        } else {
                            showNotification(data.message || 'Fejl ved gem', 'error');
                        }
                    })
                    .catch(err => showNotification('Netværksfejl: ' + err.message, 'error'));
                }

                function handleActionSubmit(e, endpoint) {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    fetch(endpoint, {
                        method: 'POST',
                        body: formData
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.status === 'ok') {
                            showNotification(data.message || 'Færdig');
                            setTimeout(() => location.reload(), 800);
                        } else {
                            showNotification(data.message || 'Fejl', 'error');
                        }
                    })
                    .catch(err => showNotification('Netværksfejl: ' + err.message, 'error'));
                }
            </script>
        </head>
        <body>
            <div id="notification" style="display:none; position:fixed; top:20px; right:20px; background:#10b981; color:white; padding:1rem 1.5rem; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.2); z-index:9999; max-width:400px; font-weight:600;">
                <span id="notification-text"></span>
            </div>
            <div class="container">
                <div class="topbar">
                    <div class="topbar-actions">
                        <nav class="nav" aria-label="Hovednavigation">
                            <a href="{{ urls.dashboard_url }}">Dashboard</a>
                            <a href="{{ urls.settings_url }}" class="active">Indstillinger</a>
                            <a href="{{ urls.history_url }}">Historik</a>
                            {% if not show_profile_switcher %}<a href="/?choose=1">Tilføj profil</a>{% endif %}
                        </nav>
                        {% if show_profile_switcher %}
                        <form class="profile-switcher" action="/" method="post">
                            <input name="driver_id" inputmode="numeric" pattern="[0-9]*" value="{{ driver_id }}" aria-label="Skift chaufførnummer">
                            <button type="submit">Skift profil</button>
                        </form>
                        {% endif %}
                    </div>
                </div>
                <section class="intro">
                    <h1>Indstillinger</h1>
                    <p>Konfiguration for chauffør {{ driver_id }}. Hver chauffør får egne filer og egne kalendereksporter.</p>
                </section>
                {% if notice %}
                <div class="notice {{ notice_type }}">{{ notice }}</div>
                {% endif %}
                <section class="panel">
                    <form onsubmit="handleSettingsSubmit(event)">
                        {% if needs_selfservice_setup %}
                        <div class="section setup-highlight span-2" style="margin-bottom:1rem;">
                            <h2>Første opsætning</h2>
                            <div class="small">Indtast først dine SelfService-oplysninger. Når de er gemt, kan du gå tilbage til dashboardet og køre din første synkronisering.</div>
                            <div class="setup-shell" style="margin-top:1rem;">
                                <div class="setup-steps">
                                    <div class="setup-step">
                                        <span class="setup-step-number">1</span>
                                        <div>
                                            <strong>Indtast login</strong>
                                            <div class="small">Brug samme brugernavn og adgangskode som i SelfService.</div>
                                        </div>
                                    </div>
                                    <div class="setup-step">
                                        <span class="setup-step-number">2</span>
                                        <div>
                                            <strong>Gem indstillinger</strong>
                                            <div class="small">Dine oplysninger gemmes kun under denne chaufførprofil.</div>
                                        </div>
                                    </div>
                                    <div class="setup-step">
                                        <span class="setup-step-number">3</span>
                                        <div>
                                            <strong>Kør første sync</strong>
                                            <div class="small">Gå tilbage til dashboardet og hent de første vagter.</div>
                                        </div>
                                    </div>
                                </div>
                                <aside class="setup-tips">
                                    <strong>Godt at vide</strong>
                                    <ul>
                                        <li>Hver chaufførprofil har sine egne filer og sin egen kalender-eksport.</li>
                                        <li>Hvis I er flere i husstanden, skal hver person bruge sit eget chaufførnummer.</li>
                                        <li>Du kan altid skifte profil i topbaren bagefter.</li>
                                    </ul>
                                </aside>
                            </div>
                        </div>
                        {% endif %}
                        <div class="section-grid">
                            <div class="section{% if needs_selfservice_setup %} setup-highlight span-2{% endif %}">
                                <h2>SelfService</h2>
                                <div class="small">RosterMate logger normalt ind skjult. Adgangskoden ligger i operativsystemets sikre nøglelager, og et synligt vindue bruges kun som reserve.</div>
                                <div class="connection-card">
                                    <span class="connection-status {{ 'connected' if has_selfservice_session else 'disconnected' }}">{{ '✓ Forbundet til SelfService' if has_selfservice_session else 'Ikke forbundet endnu' }}</span>
                                    <div class="field">
                                        <label for="url">SelfService URL</label>
                                        <input id="url" name="url" value="{{ settings.url }}">
                                        <div class="field-hint">Normalt behøver du ikke ændre denne adresse.</div>
                                    </div>
                                    <div class="inline-actions">
                                        <a class="ghost-button" href="{{ urls.wizard_relogin_url }}">Åbn opsætningsguide</a>
                                        <a class="ghost-button" href="{{ urls.wizard_relogin_url }}">Skift SelfService-konto</a>
                                    </div>
                                    {% if needs_selfservice_setup %}
                                    <div class="field-hint">Indtast login i opsætningsguiden. Adgangskoden gemmes aldrig i settings.json.</div>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="section">
                                <h2>Synkronisering</h2>
                                <div class="small">Styr hvor langt frem appen henter, og hvordan gamle vagter håndteres.</div>
                                <div class="field">
                                    <label for="employment_type">Arbejdstype</label>
                                    <select id="employment_type" name="employment_type">
                                        <option value="ramme_ansat" {% if settings.employment_type == 'ramme_ansat' %}selected{% endif %}>Ramme ansat (dagligt mellem kl. 12 og 14)</option>
                                        <option value="fast_turnus" {% if settings.employment_type == 'fast_turnus' %}selected{% endif %}>Fast turnus (tirsdag og torsdag mellem kl. 9 og 16)</option>
                                        <option value="timeloennet" {% if settings.employment_type == 'timeloennet' %}selected{% endif %}>Timelønnet (dagligt mellem kl. 9 og 16)</option>
                                    </select>
                                    <div class="field-hint">Denne profil har faste, tilfældigt valgte tider: {{ automatic_schedule }}.</div>
                                </div>
                                <div class="field">
                                    <label for="days_ahead">Dage frem</label>
                                    <input id="days_ahead" name="days_ahead" type="number" min="1" max="365" value="{{ settings.days_ahead }}">
                                </div>
                                <label class="row"><input type="checkbox" name="remove_old_shifts" value="true" {% if settings.remove_old_shifts %}checked{% endif %}> Fjern gamle vagter ved sync</label>
                                <div class="field">
                                    <label for="calendar_public_base_url">Offentlig kalenderadresse</label>
                                    <input id="calendar_public_base_url" name="calendar_public_base_url" value="{{ settings.calendar_public_base_url or '' }}" placeholder="https://kalender.example.dk">
                                    <div class="field-hint">Lad feltet være tomt for kun at bruge kalenderen på lokalnetværket.</div>
                                </div>
                            </div>
                            <div class="section span-2">
                                <h2>Lokal server</h2>
                                <div class="small">Porten gælder for hele installationen og alle chaufførprofiler.</div>
                                <div class="field">
                                    <label for="app_port">Port</label>
                                    <input id="app_port" name="app_port" type="number" min="1024" max="65535" value="{{ app_port }}">
                                    <div class="field-hint">En ændring træder i kraft, næste gang RosterMate genstartes. Kalenderlinks og opsætningsguiden følger automatisk den valgte port.</div>
                                </div>
                            </div>
                        </div>
                        <div class="helper-links">
                            <button type="submit">Gem indstillinger</button>
                            <a href="{{ urls.dashboard_url }}">Tilbage til dashboard</a>
                            <a href="{{ urls.history_url }}">Åbn historik</a>
                        </div>
                    </form>
                </section>
            </div>
        </body>
        </html>
        """,
        driver_id=safe_driver_id,
        settings=settings,
        notice=notice,
        notice_type=notice_type,
        urls=urls,
        has_selfservice_session=has_selfservice_session,
        show_profile_switcher=show_profile_switcher,
        app_port=app_port,
        automatic_schedule=schedule_summary(settings),
    )


@app.route("/<driver_id>/settings", methods=["POST"])
def settings_route(driver_id: str) -> tuple[Any, int]:
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)

    employment_type = request.form.get("employment_type", settings.get("employment_type", "ramme_ansat"))
    if employment_type not in ("ramme_ansat", "fast_turnus", "timeloennet"):
        employment_type = "ramme_ansat"

    remove_old_shifts = request.form.get("remove_old_shifts") == "true"
    current_port = application_port()
    requested_port = valid_port(request.form.get("app_port", current_port))
    if requested_port is None:
        return jsonify({"status": "error", "message": "Porten skal være mellem 1024 og 65535."}), 400
    if requested_port != current_port and not port_is_available(requested_port):
        return jsonify({"status": "error", "message": f"Port {requested_port} bruges allerede af et andet program."}), 409
    updated_settings = {
        **settings,
        "url": request.form.get("url", settings.get("url", "")),
        "user": request.form.get("user", settings.get("user", "")),
        "pass": request.form.get("pass", settings.get("pass", "")),
        "days_ahead": int(request.form.get("days_ahead", settings.get("days_ahead", 7))),
        "remove_old_shifts": remove_old_shifts,
        "employment_type": employment_type,
        "calendar_public_base_url": request.form.get(
            "calendar_public_base_url", settings.get("calendar_public_base_url", "")
        ).strip().rstrip("/"),
    }
    submitted_password = str(request.form.get("pass", ""))
    if submitted_password:
        try:
            set_password(safe_driver_id, submitted_password)
            if get_password(safe_driver_id) != submitted_password:
                raise RuntimeError("adgangskoden kunne ikke læses tilbage efter lagring")
        except Exception as exc:
            return jsonify({
                "status": "error",
                "message": f"Adgangskoden kunne ikke gemmes i operativsystemets sikre nøglelager: {exc}",
            }), 500
    save_driver_settings(safe_driver_id, updated_settings)
    save_port(requested_port, root=DATA_DIR.parent)
    port_changed = requested_port != current_port
    message = "Indstillinger gemt. Genstart RosterMate for at bruge den nye port." if port_changed else "Indstillinger gemt"
    return jsonify({
        "status": "ok",
        "message": message,
        "employment_type": employment_type,
        "port": requested_port,
        "restart_required": port_changed,
        "next_url": f"http://localhost:{requested_port}/",
    })


@app.route("/<driver_id>/history")
def history_page(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    session["last_driver_id"] = safe_driver_id
    history = load_history(paths["history_path"])
    urls = driver_urls(safe_driver_id)
    formatted_history = []
    show_profile_switcher = len(list_driver_ids()) > 1
    for entry in reversed(history):
        formatted_history.append(
            {
                "timestamp": format_timestamp(entry.get("timestamp")),
                "summary": entry.get("summary", ""),
                "changes": [describe_change(change) for change in entry.get("changes", []) if isinstance(change, dict)],
            }
        )
    return render_template_string(
        """
        <!doctype html>
        <html lang="da">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>RosterMate Historik</title>
            <style>
                :root {
                    --bg: #eef4fb;
                    --panel: #ffffff;
                    --panel-2: #f5f9ff;
                    --text: #14213d;
                    --muted: #64748b;
                    --accent-2: #10213c;
                    --border: #dbe6f2;
                    --shadow: 0 18px 40px rgba(16, 33, 60, 0.08);
                    --success-bg: #e8f7ef;
                    --success-text: #166534;
                    --warning-bg: #fff4db;
                    --warning-text: #9a6700;
                    --danger-bg: #fce9e7;
                    --danger-text: #b42318;
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: linear-gradient(180deg, #f7fbff 0%, var(--bg) 100%);
                    color: var(--text);
                }
                a { color: inherit; text-decoration: none; }
                .container { max-width: 980px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
                .topbar { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: 1rem; }
                .topbar-actions { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
                .nav { display: flex; gap: 0.7rem; flex-wrap: wrap; }
                .nav a {
                    padding: 0.7rem 1rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.82);
                    border: 1px solid var(--border);
                    font-weight: 600;
                }
                .nav a.active { background: var(--accent-2); color: white; }
                .profile-switcher {
                    display: flex;
                    align-items: center;
                    gap: 0.55rem;
                    padding: 0.45rem;
                    border-radius: 999px;
                    background: rgba(255, 255, 255, 0.82);
                    border: 1px solid var(--border);
                }
                .profile-switcher input {
                    width: 112px;
                    padding: 0.65rem 0.8rem;
                    border-radius: 999px;
                    border: 1px solid var(--border);
                    font: inherit;
                }
                .profile-switcher button {
                    border: none;
                    border-radius: 999px;
                    background: var(--accent-2);
                    color: white;
                    padding: 0.75rem 1rem;
                    font: inherit;
                    font-weight: 700;
                    cursor: pointer;
                }
                .hero {
                    background: linear-gradient(120deg, var(--accent-2) 0%, #17355f 60%, #0f766e 100%);
                    color: white;
                    border-radius: 24px;
                    padding: 1.3rem;
                    margin-bottom: 1rem;
                    box-shadow: 0 24px 48px rgba(16, 33, 60, 0.16);
                }
                .hero h1 { margin: 0 0 0.35rem; }
                .hero p { margin: 0; opacity: 0.86; }
                .timeline { display: grid; gap: 1rem; }
                .entry {
                    background: var(--panel);
                    border: 1px solid var(--border);
                    border-radius: 22px;
                    padding: 1.15rem 1.2rem;
                    box-shadow: var(--shadow);
                }
                .entry-head {
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                    align-items: flex-start;
                    margin-bottom: 0.65rem;
                }
                .small { color: var(--muted); font-size: 0.92rem; }
                .change-list { list-style: none; padding: 0; margin: 0.75rem 0 0; display: grid; gap: 0.65rem; }
                .change-item {
                    display: flex;
                    justify-content: space-between;
                    gap: 0.8rem;
                    align-items: center;
                    border: 1px solid var(--border);
                    border-radius: 16px;
                    padding: 0.75rem 0.9rem;
                    background: var(--panel-2);
                }
                .badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 0.28rem 0.65rem;
                    border-radius: 999px;
                    font-size: 0.78rem;
                    font-weight: 700;
                }
                .badge-added { background: var(--success-bg); color: var(--success-text); }
                .badge-removed { background: var(--danger-bg); color: var(--danger-text); }
                .badge-changed { background: var(--warning-bg); color: var(--warning-text); }
                @media (max-width: 700px) {
                    .topbar,
                    .topbar-actions,
                    .profile-switcher,
                    .entry-head,
                    .change-item {
                        flex-direction: column;
                        align-items: stretch;
                    }
                    .profile-switcher input,
                    .profile-switcher button {
                        width: 100%;
                    }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="topbar">
                    <div class="topbar-actions">
                        <nav class="nav" aria-label="Hovednavigation">
                            <a href="{{ urls.dashboard_url }}">Dashboard</a>
                            <a href="{{ urls.settings_url }}">Indstillinger</a>
                            <a href="{{ urls.history_url }}" class="active">Historik</a>
                            {% if not show_profile_switcher %}<a href="/?choose=1">Tilføj profil</a>{% endif %}
                        </nav>
                        {% if show_profile_switcher %}
                        <form class="profile-switcher" action="/" method="post">
                            <input name="driver_id" inputmode="numeric" pattern="[0-9]*" value="{{ driver_id }}" aria-label="Skift chaufførnummer">
                            <button type="submit">Skift profil</button>
                        </form>
                        {% endif %}
                    </div>
                </div>
                <section class="hero">
                    <h1>Historik</h1>
                    <p>Alle importer og synkroniseringer for chauffør {{ driver_id }} samlet i en mere læsbar tidslinje.</p>
                </section>
                <section class="timeline">
                {% for entry in history %}
                    <article class="entry">
                        <div class="entry-head">
                            <div>
                                <strong>{{ entry.timestamp }}</strong>
                                <p>{{ entry.summary }}</p>
                            </div>
                            <span class="small">{{ entry.changes|length }} ændringer</span>
                        </div>
                        {% if entry.changes %}
                        <ul class="change-list">
                            {% for change in entry.changes %}
                            <li class="change-item">
                                <div>
                                    <span class="badge {{ change.badge_class }}">{{ change.badge_text }}</span>
                                    <strong style="display:block; margin-top:0.45rem;">{{ change.title }}</strong>
                                    <div class="small">{{ change.detail }}</div>
                                </div>
                                <span class="small">{{ change.date_label }}</span>
                            </li>
                            {% endfor %}
                        </ul>
                        {% endif %}
                    </article>
                {% else %}
                    <article class="entry">
                        <strong>Ingen historik endnu</strong>
                        <p class="small">Kør en import eller synkronisering for at opbygge tidslinjen.</p>
                    </article>
                {% endfor %}
                </section>
            </div>
        </body>
        </html>
        """,
        driver_id=safe_driver_id,
        history=formatted_history,
        urls=urls,
        show_profile_switcher=show_profile_switcher,
    )


@app.route("/<driver_id>/calendar.ics")
def calendar_file(driver_id: str) -> Any:
    paths = get_driver_paths(driver_id)
    if not paths["ics_path"].exists():
        return jsonify({"status": "error", "message": "Kalenderfilen findes ikke endnu"}), 404
    response = send_file(paths["ics_path"], mimetype="text/calendar; charset=utf-8", as_attachment=False, conditional=False)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/<driver_id>/backup", methods=["POST"])
def backup(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    backup_path = create_backup(paths["history_path"], paths["backup_dir"])
    return jsonify({"status": "ok", "message": "Backup oprettet", "path": str(backup_path)})


@app.route("/health")
def health() -> tuple[Any, int]:
    ensure_storage()
    return jsonify({"status": "ok", "version": APP_VERSION}), 200


if __name__ == "__main__":
    start_automatic_sync_worker()
    app.run(host=os.environ.get("ROSTERMATE_HOST", "0.0.0.0"), port=application_port(), debug=False, use_reloader=False)
