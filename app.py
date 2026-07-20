from __future__ import annotations

import json
import os
import re
import secrets
import socket
import shutil
import hashlib
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, session, url_for

from dashboard import should_show_first_run, should_show_welcome_back
from launch_agent import sync_launch_agent_preference
from login import launch_authenticated_context, login_manager, read_stable_page_content, save_session_storage
from session import SelfServiceSessionStore
from settings import apply_wizard_preferences, with_setup_defaults
from sync import build_sync_preview, fetch_status_is_error, run_initial_sync
from wizard import FIRST_RUN_TEMPLATE, WIZARD_PREFERENCES_TEMPLATE

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "rostermate-dev-secret-change-me")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "backups"
OUTPUT_DIR = BASE_DIR / "output"
HISTORY_PATH = DATA_DIR / "history.json"
PLAN_PATH = DATA_DIR / "plan.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
SCHEDULE_PATH = OUTPUT_DIR / "schedule.json"
EVENTS_STORE_PATH = OUTPUT_DIR / "events_store.json"
CHANGES_PATH = OUTPUT_DIR / "changes.json"
ICS_PATH = OUTPUT_DIR / "vagter.ics"
GOOGLE_TOKEN_PATH = DATA_DIR / "google_token.json"
GOOGLE_SYNC_STATE_PATH = DATA_DIR / "google_sync_state.json"
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
LOCAL_TIMEZONE = "Europe/Copenhagen"
APP_VERSION = "1.1.0"


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
        "google_token_path": data_dir / "google_token.json",
        "google_sync_state_path": data_dir / "google_sync_state.json",
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
    try:
        days_ahead = int(env_values.get("DAYS_AHEAD", stored.get("days_ahead", 7)))
    except (TypeError, ValueError):
        days_ahead = 7

    try:
        run_every_minutes = int(env_values.get("RUN_EVERY_MINUTES", stored.get("run_every_minutes", 60)))
    except (TypeError, ValueError):
        run_every_minutes = 60

    employment_type = stored.get("employment_type", "ramme_ansat")
    if employment_type not in ("ramme_ansat", "fast_turnus"):
        employment_type = "ramme_ansat"

    return with_setup_defaults({
        **stored,
        "url": env_values.get("SELFSERVICE_URL", stored.get("url", "https://selfservicedanmark.tidebus.dk")),
        "user": env_values.get("SELFSERVICE_USER", stored.get("user", "")),
        "pass": env_values.get("SELFSERVICE_PASS", stored.get("pass", "")),
        "days_ahead": max(1, min(days_ahead, 365)),
        "run_every_minutes": max(1, min(run_every_minutes, 10080)),
        "remove_old_shifts": _coerce_bool(env_values.get("REMOVE_OLD_SHIFTS", stored.get("remove_old_shifts", False))),
        "employment_type": employment_type,
        "google_client_id": env_values.get("GOOGLE_CLIENT_ID", stored.get("google_client_id", "")),
        "google_client_secret": env_values.get("GOOGLE_CLIENT_SECRET", stored.get("google_client_secret", "")),
        "google_calendar_id": env_values.get("GOOGLE_CALENDAR_ID", stored.get("google_calendar_id", "primary")),
        "google_redirect_uri": env_values.get("GOOGLE_REDIRECT_URI", stored.get("google_redirect_uri", "")),
    })


def save_driver_settings(driver_id: str, settings: dict[str, Any]) -> None:
    paths = get_driver_paths(driver_id)
    save_json(paths["settings_path"], settings)


def driver_urls(driver_id: str) -> dict[str, str]:
    safe_driver_id = normalize_driver_id(driver_id)
    base_path = f"/{safe_driver_id}"
    return {
        "base_path": base_path,
        "dashboard_url": f"{base_path}/",
        "wizard_url": f"{base_path}/wizard",
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
        "google_connect_url": f"{base_path}/google/connect",
        "google_sync_url": f"{base_path}/google/sync",
        "google_disconnect_url": f"{base_path}/google/disconnect",
    }


def calculate_next_sync(employment_type: str) -> str:
    """Calculate next scheduled sync time based on employment type."""
    now = datetime.now()
    weekday_names = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]

    if employment_type == "fast_turnus":
        # Fast turnus: sync on Tuesday and Friday at 14:00
        current_weekday = now.weekday()  # Monday=0, Sunday=6
        current_hour = now.hour

        # Tuesday (1) and Friday (4)
        sync_days = [1, 4]
        sync_hour = 14

        # Find next sync day
        next_sync = None

        # Check if today is a sync day and time hasn't passed
        if current_weekday in sync_days and current_hour < sync_hour:
            next_sync = now.replace(hour=sync_hour, minute=0, second=0, microsecond=0)
        else:
            # Find next sync day
            days_ahead = 0
            for _ in range(7):
                check_day = (current_weekday + days_ahead) % 7
                if check_day in sync_days:
                    if days_ahead == 0 and current_hour >= sync_hour:
                        days_ahead = 1
                        continue
                    next_sync_date = now + timedelta(days=days_ahead)
                    next_sync = next_sync_date.replace(hour=sync_hour, minute=0, second=0, microsecond=0)
                    break
                days_ahead += 1

        if next_sync and next_sync <= now:
            # If calculated time is in the past, move to next cycle
            next_sync = next_sync + timedelta(days=1)
            while next_sync.weekday() not in sync_days:
                next_sync = next_sync + timedelta(days=1)

        if next_sync:
            day_name = weekday_names[next_sync.weekday()]
            return f"{day_name} kl. {next_sync.strftime('%H:%M')}"
        return "Ukendt"
    else:
        # Ramme ansat: sync every hour
        next_hour = now + timedelta(hours=1)
        day_name = weekday_names[next_hour.weekday()]
        return f"{day_name} kl. {next_hour.strftime('%H:%M')}"


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
    """Return the next calendar events, excluding stale and invalid entries."""
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

    return sorted(
        upcoming,
        key=lambda item: (str(item.get("date", "")), str(item.get("start", ""))),
    )[:max(0, limit)]


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


def google_redirect_uri(settings: dict[str, Any], driver_id: str, base_url: str | None = None) -> str:
    configured = str(settings.get("google_redirect_uri", "")).strip()
    if configured:
        return configured
    if base_url:
        return f"{base_url.rstrip('/')}/{normalize_driver_id(driver_id)}/google/callback"
    return f"http://127.0.0.1:8080/{normalize_driver_id(driver_id)}/google/callback"


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
        base_url = f"http://{local_network_address()}:8080"
    return f"{base_url}/{normalize_driver_id(driver_id)}/calendar.ics?token={token}"


def valid_google_client_id(value: Any) -> bool:
    client_id = str(value or "").strip()
    return bool(re.fullmatch(r"\d+-[a-z0-9_-]+\.apps\.googleusercontent\.com", client_id, re.IGNORECASE))


def google_integration_status(settings: dict[str, Any], driver_id: str, token_path: Path, base_url: str | None = None) -> dict[str, Any]:
    has_client_id = bool(str(settings.get("google_client_id") or "").strip())
    client_id_valid = valid_google_client_id(settings.get("google_client_id"))
    credentials_ready = bool(client_id_valid and settings.get("google_client_secret"))
    token_data = load_json(token_path, {})
    connected = bool(token_data.get("refresh_token") or token_data.get("token"))
    calendar_id = str(settings.get("google_calendar_id") or "primary")
    if connected:
        summary = f"Forbundet til kalender: {calendar_id}"
        tone = "success"
    elif credentials_ready:
        summary = "Google OAuth er klar. Log ind for at forbinde kalenderen."
        tone = "info"
    elif has_client_id and not client_id_valid:
        summary = "OAuth Client ID er ugyldigt. Indsæt det fulde Google Client ID, som slutter med .apps.googleusercontent.com."
        tone = "warning"
    else:
        summary = "Tilføj Google OAuth Client ID og Client Secret for at aktivere Google Calendar-sync."
        tone = "warning"

    return {
        "credentials_ready": credentials_ready,
        "client_id_valid": client_id_valid,
        "connected": connected,
        "calendar_id": calendar_id,
        "redirect_uri": google_redirect_uri(settings, driver_id, base_url),
        "summary": summary,
        "tone": tone,
    }


def google_dependencies_available() -> tuple[bool, str]:
    try:
        from google_auth_oauthlib.flow import Flow  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
        return True, ""
    except ImportError as exc:
        return False, str(exc)


def create_google_flow(settings: dict[str, Any], driver_id: str, base_url: str, state: str | None = None) -> Any:
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.get("google_client_id", ""),
            "client_secret": settings.get("google_client_secret", ""),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [google_redirect_uri(settings, driver_id, base_url)],
        }
    }
    flow = Flow.from_client_config(client_config, scopes=GOOGLE_SCOPES, state=state)
    flow.redirect_uri = google_redirect_uri(settings, driver_id, base_url)
    return flow


def save_google_token(token_path: Path, credentials: Any) -> None:
    save_json(token_path, json.loads(credentials.to_json()))


def load_google_credentials(token_path: Path) -> Any:
    token_data = load_json(token_path, {})
    if not token_data:
        return None

    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.credentials import Credentials

    credentials = Credentials.from_authorized_user_info(token_data, GOOGLE_SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
        save_google_token(token_path, credentials)
    return credentials


def make_google_event_key(event: dict[str, Any]) -> str:
    raw_key = "|".join(
        [
            str(event.get("date", "")),
            str(event.get("title", "")),
            str(event.get("start", "")),
            str(event.get("end", "")),
            str(event.get("all_day", False)),
        ]
    )
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()


def build_google_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    title = str(event.get("title", "Vagt"))
    payload = {
        "summary": title,
        "description": f"Synkroniseret fra RosterMate\nDato: {event.get('date', '')}",
        "extendedProperties": {"private": {"rostermate_managed": "true"}},
    }
    if event.get("all_day"):
        try:
            start_day = date.fromisoformat(str(event.get("date", "")))
        except ValueError:
            start_day = date.today()
        payload["start"] = {"date": start_day.isoformat()}
        payload["end"] = {"date": (start_day + timedelta(days=1)).isoformat()}
    else:
        payload["start"] = {"dateTime": str(event.get("start", "")), "timeZone": LOCAL_TIMEZONE}
        payload["end"] = {"dateTime": str(event.get("end", event.get("start", ""))), "timeZone": LOCAL_TIMEZONE}
    return payload


def sync_google_calendar_events(events: list[dict[str, Any]], settings: dict[str, Any], token_path: Path, sync_state_path: Path) -> dict[str, int]:
    credentials = load_google_credentials(token_path)
    if credentials is None:
        raise RuntimeError("Google-kontoen er ikke forbundet endnu")

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    calendar_id = str(settings.get("google_calendar_id") or "primary")
    service = build("calendar", "v3", credentials=credentials)
    state = load_json(sync_state_path, {"event_map": {}})
    event_map = state.get("event_map", {}) if isinstance(state, dict) else {}

    inserted = 0
    updated = 0
    deleted = 0
    current_keys: set[str] = set()

    for event in events:
        event_key = make_google_event_key(event)
        current_keys.add(event_key)
        payload = build_google_event_payload(event)
        google_event_id = event_map.get(event_key)

        if google_event_id:
            try:
                service.events().update(calendarId=calendar_id, eventId=google_event_id, body=payload).execute()
                updated += 1
                continue
            except HttpError as exc:
                if getattr(exc, "status_code", None) != 404 and getattr(exc.resp, "status", None) != 404:
                    raise

        created = service.events().insert(calendarId=calendar_id, body=payload).execute()
        event_map[event_key] = created.get("id", "")
        inserted += 1

    for stale_key in list(event_map.keys()):
        if stale_key in current_keys:
            continue
        google_event_id = event_map.get(stale_key)
        if not google_event_id:
            event_map.pop(stale_key, None)
            continue
        try:
            service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
            deleted += 1
        except HttpError as exc:
            if getattr(exc, "status_code", None) != 404 and getattr(exc.resp, "status", None) != 404:
                raise
        event_map.pop(stale_key, None)

    save_json(sync_state_path, {"event_map": event_map, "calendar_id": calendar_id})
    return {"inserted": inserted, "updated": updated, "deleted": deleted}


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

    return {
        "id": title,
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

    if remove_old_shifts:
        filtered_existing = [event for event in existing_events if _is_in_window(event.get("date"), window_start, window_end)]
        updated_events = filtered_existing + new_events
    else:
        updated_events = list(existing_events)
        seen_ids: set[str] = {event.get("id", "") for event in updated_events if event.get("id")}
        for event in new_events:
            event_id = event.get("id") or event.get("title") or ""
            if event_id in seen_ids:
                continue
            # Filtrér nye events til kun at være inden for window
            if not _is_in_window(event.get("date"), window_start, window_end):
                continue
            updated_events.append(event)
            seen_ids.add(event_id)

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


def fetch_selfservice_schedule(days_ahead: int, driver_id: str) -> tuple[list[dict[str, Any]], str]:
    paths = get_driver_paths(driver_id)
    settings = load_settings(driver_id)
    session_store = SelfServiceSessionStore.from_paths(driver_id, paths)

    try:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return [], f"Afhængighed mangler: {exc}"

    html = None
    try:
        with sync_playwright() as p:
            browser, context = launch_authenticated_context(p, session_store, headless=True)
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

            if "Username" in initial_html or "Password" in initial_html:
                if not settings.get("user") or not settings.get("pass"):
                    context.close()
                    if browser is not None:
                        browser.close()
                    return [], "SelfService-sessionen er udløbet, og gemte loginoplysninger mangler. Forbind via opsætningsguiden igen."

                page.fill("input#Username", settings["user"])
                page.fill("input#Password", settings["pass"])

                selectors_to_try = [
                    "#LoginButton",
                    "div.DarkButton",
                    "button[type='submit']",
                    "input[type='submit']",
                ]

                clicked = False
                for selector in selectors_to_try:
                    try:
                        page.click(selector, timeout=5000)
                        clicked = True
                        break
                    except:
                        pass

                if not clicked:
                    context.close()
                    if browser is not None:
                        browser.close()
                    return [], "Kunne ikke finde login-knap"

                try:
                    page.wait_for_url("**/Assignments**", timeout=15000)
                except:
                    pass

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

            html = read_stable_page_content(page)
            if html is None:
                context.close()
                if browser is not None:
                    browser.close()
                return [], "SelfService navigerer stadig. Prøv synkroniseringen igen om et øjeblik."

            debug_path = paths["output_dir"] / "debug_html.log"
            with debug_path.open("w", encoding="utf-8") as f:
                f.write(html[:100000])

            context.close()
            if browser is not None:
                browser.close()

    except Exception as exc:
        return [], f"Fejl ved henting af schedule: {str(exc)}"

    if not html:
        return [], "Kunne ikke hente HTML fra SelfService"

    # Parse HTML med BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Tjek om vi kunne logge ind (hvis vi er tilbage på login-siden)
    if "Username" in html and "Password" in html:
        return [], "Login mislykkedes - tjek brugernavn og adgangskode"

    if "Arbejdskalender" not in html:
        return [], "Siden loadede ikke korrekt - ikke på arbejdskalender siden"

    # Søg efter vagt-data i kalenderen
    shifts_with_dates: list[dict[str, Any]] = []
    seen_shifts: set[str] = set()

    # Enkel strategi: Søg efter alle elementer der indeholder vagter
    all_text = soup.get_text(" ", strip=True)

    # Søg efter dag-nummer efterfulgt af vagt-info
    # Mønster: "08 Fri Normal tid: 0h00" eller "09 Vacation Normal tid: 7h24"

    # Find alle dag-blokke (dag-nummer efterfulgt af indhold)
    today = date.today()

    # Split efter dag-numre 1-31 og find vagter
    day_pattern = re.compile(r'(\d{1,2})\s+(Fri|Vacation|(\d+\s+ID:\s+[A-Za-z_]+))', re.IGNORECASE)

    for match in day_pattern.finditer(all_text):
        day_num = int(match.group(1))
        vagt_type = match.group(2)

        if day_num < 1 or day_num > 31:
            continue

        # Beregn dato
        try:
            shift_date = today.replace(day=day_num)
            # Hvis dagen er før idag, antag næste måned
            if shift_date < today:
                next_month = today.month + 1 if today.month < 12 else 1
                next_year = today.year if today.month < 12 else today.year + 1
                shift_date = shift_date.replace(month=next_month, year=next_year)
        except ValueError:
            continue

        shift_date_str = shift_date.strftime("%Y-%m-%d")

        # Håndter Fri
        if vagt_type.lower() == "fri":
            shift_key = f"Fri_{shift_date_str}"
            if shift_key not in seen_shifts:
                seen_shifts.add(shift_key)
                shifts_with_dates.append({
                    "id": "Fri",
                    "from": "00:00",
                    "to": "00:00",
                    "date": shift_date_str,
                })

        # Håndter Vacation
        elif vagt_type.lower() == "vacation":
            shift_key = f"Vacation_{shift_date_str}"
            if shift_key not in seen_shifts:
                seen_shifts.add(shift_key)
                shifts_with_dates.append({
                    "id": "Vacation",
                    "from": "00:00",
                    "to": "00:00",
                    "date": shift_date_str,
                })

        # Håndter DO_afl vagter
        else:
            id_match = re.search(r"(\d+\s+ID:\s+[A-Za-z_]+)", match.group(0) + all_text[match.end():match.end()+50])
            if id_match:
                id_part = id_match.group(1).strip()
                # Find tider efter ID
                times_after = re.findall(r"(\d{1,2}):(\d{2})", all_text[match.end():match.end()+200])
                if len(times_after) >= 2:
                    from_time = f"{times_after[0][0]}:{times_after[0][1]}"
                    to_time = f"{times_after[1][0]}:{times_after[1][1]}"
                else:
                    from_time = "00:00"
                    to_time = "00:00"

                shift_key = f"{id_part}_{from_time}_{to_time}_{shift_date_str}"
                if shift_key not in seen_shifts:
                    seen_shifts.add(shift_key)
                    shifts_with_dates.append({
                        "id": id_part[:40],
                        "from": from_time,
                        "to": to_time,
                        "date": shift_date_str,
                    })

    if not shifts_with_dates:
        return [], "Ingen vagter fundet i kalenderen - muligvis ingen vagter planlagt"

    today = date.today()
    events: list[dict[str, Any]] = []

    # Begræns til days_ahead vagter
    max_shifts = days_ahead * 3  # Ca. 3 vagter per dag i værste fald
    shifts_to_process = shifts_with_dates[:max_shifts]

    # Konverter vagter til events, brug allerede hentede datoer
    for shift in shifts_to_process:
        # Hvis vi har hentet en dato fra HTML, brug den - ellers fordel over dage
        shift_date = shift.get("date") or (today + timedelta(days=len(events) // 2)).strftime("%Y-%m-%d")
        events.append(build_event_from_shift(shift, shift_date))

    return events, f"Synkronisering gennemført - {len(shifts_to_process)} vagter hentet"


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
        if should_show_first_run(settings, session_store) or should_show_welcome_back(settings, session_store):
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
            if should_show_first_run(settings, session_store) or should_show_welcome_back(settings, session_store):
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
    welcome_back = should_show_welcome_back(settings, session_store)

    if session_store.has_saved_session() and not settings.get("wizard_completed"):
        return redirect(urls["wizard_preferences_url"])

    if not should_show_first_run(settings, session_store) and not welcome_back:
        return redirect(urls["dashboard_url"])

    return render_template_string(
        FIRST_RUN_TEMPLATE,
        driver_id=safe_driver_id,
        urls=urls,
        welcome_back=welcome_back,
        version=APP_VERSION,
        last_sync=format_timestamp(history[-1].get("timestamp") if history else None),
    )


@app.route("/<driver_id>/wizard/connect", methods=["POST"])
def wizard_connect(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    if request.args.get("reset") == "1":
        login_manager.clear_driver_session(session_store)

    flow = login_manager.start(safe_driver_id, settings["url"], session_store)
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
        login_manager.update(flow_id, state="syncing", message="⟳ Synkroniserer…")
        try:
            settings = load_settings(safe_driver_id)
            result = run_initial_sync(
                safe_driver_id,
                settings,
                paths,
                fetch_selfservice_schedule,
                sync_schedule,
                write_outputs,
                load_json,
                load_history,
                save_history,
            )
        except Exception as exc:
            flow = login_manager.update(flow_id, state="error", message=str(exc))
        else:
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
    if should_show_first_run(settings, session_store):
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
    google_status = google_integration_status(settings, safe_driver_id, paths["google_token_path"])
    urls = driver_urls(safe_driver_id)
    calendar_subscription_url = calendar_subscription_address(
        safe_driver_id,
        str(settings["calendar_access_token"]),
        str(settings.get("calendar_public_base_url") or ""),
    )
    needs_selfservice_setup = not session_store.has_saved_session()
    show_profile_switcher = len(list_driver_ids()) > 1

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
                    setTimeout(() => {
                        notif.style.display = 'none';
                        if (type === 'success') {
                            setTimeout(() => location.reload(), 1000);
                        }
                    }, 3000);
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
                        if (data.status === 'ok') {
                            showNotification(data.message || 'Færdig', 'success');
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
                                    <a class="button-link secondary" href="{{ urls.settings_url }}">Åbn indstillinger</a>
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
                                <h2>De næste 7 kalenderposter</h2>
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
                                    <div class="small" style="margin-top:0.7rem; overflow-wrap:anywhere;">{{ calendar_subscription_url }}</div>
                                </div>
                                <div class="quick-card">
                                    <strong>Google Calendar</strong>
                                    <div class="small">{{ google_status.summary }}</div>
                                    <div style="margin-top:0.8rem;"><a class="button-link ghost" href="{{ urls.settings_url }}">Forbind</a></div>
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
        next_sync=calculate_next_sync(settings["employment_type"]),
        employment_type=settings["employment_type"],
        employment_type_label="Ansættelsesform",
        employment_type_display="Ramme ansat" if settings["employment_type"] == "ramme_ansat" else "Fast turnus",
        days_ahead=settings["days_ahead"],
        remove_old_shifts=settings["remove_old_shifts"],
        event_count=len(events),
        upcoming_shifts=upcoming_shifts,
        dashboard_changes=dashboard_changes,
        history_count=history_count,
        ics_ready=ics_ready,
        google_status=google_status,
        urls=urls,
        calendar_subscription_url=calendar_subscription_url,
        software=software_info(),
        show_profile_switcher=show_profile_switcher,
        needs_selfservice_setup=needs_selfservice_setup,
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
    remove_old_shifts = request.form.get("remove_old_shifts") == "true"

    existing_events = load_json(paths["events_store_path"], [])
    new_events, status_message = fetch_selfservice_schedule(days_ahead, safe_driver_id)

    if not new_events and (not existing_events or fetch_status_is_error(status_message)):
        return jsonify({"status": "error", "message": status_message}), 400

    window_start = date.today().strftime("%Y-%m-%d")
    window_end = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    updated_events, changes = sync_schedule(existing_events, new_events, window_start, window_end, remove_old_shifts, paths["output_dir"])
    write_outputs(updated_events, changes, paths["output_dir"])

    history = load_history(paths["history_path"])
    history.append({"timestamp": datetime.now().isoformat(), "summary": f"Synkroniserede {len(new_events)} vagter", "changes": changes})
    save_history(history, paths["history_path"])
    save_driver_settings(safe_driver_id, {**settings, "days_ahead": days_ahead, "remove_old_shifts": remove_old_shifts})

    return jsonify({"status": "ok", "message": status_message, "events": updated_events, "changes": changes})


@app.route("/<driver_id>/settings-page")
def settings_page(driver_id: str) -> str:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    session["last_driver_id"] = safe_driver_id
    settings = load_settings(safe_driver_id)
    session_store = SelfServiceSessionStore.from_paths(safe_driver_id, paths)
    notice = request.args.get("notice", "")
    notice_type = request.args.get("notice_type", "success")
    google_status = google_integration_status(settings, safe_driver_id, paths["google_token_path"], request.url_root)
    google_available, google_dependency_error = google_dependencies_available()
    urls = driver_urls(safe_driver_id)
    has_selfservice_session = session_store.has_saved_session()
    needs_selfservice_setup = not has_selfservice_session
    show_profile_switcher = len(list_driver_ids()) > 1
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
                .google-actions {
                    display: flex;
                    gap: 0.7rem;
                    flex-wrap: wrap;
                    margin-top: 1rem;
                }
                .google-actions form { margin: 0; }
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
                    .google-actions,
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
                    setTimeout(() => {
                        notif.style.display = 'none';
                    }, 3000);
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
                                <div class="small">RosterMate bruger den rigtige SelfService-side i et separat vindue og gemmer kun browser-sessionen lokalt.</div>
                                <div class="connection-card">
                                    <span class="connection-status {{ 'connected' if has_selfservice_session else 'disconnected' }}">{{ '✓ Forbundet til SelfService' if has_selfservice_session else 'Ikke forbundet endnu' }}</span>
                                    <div class="field">
                                        <label for="url">SelfService URL</label>
                                        <input id="url" name="url" value="{{ settings.url }}">
                                        <div class="field-hint">Normalt behøver du ikke ændre denne adresse.</div>
                                    </div>
                                    <div class="inline-actions">
                                        <a class="ghost-button" href="{{ urls.wizard_url }}">Åbn First Run Wizard</a>
                                        <a class="ghost-button" href="{{ urls.wizard_url }}">Forbind igen</a>
                                    </div>
                                    {% if needs_selfservice_setup %}
                                    <div class="field-hint">Loginfelter vises ikke her. Brug wizard-flowet til at logge ind sikkert via den officielle SelfService-side.</div>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="section">
                                <h2>Synkronisering</h2>
                                <div class="small">Styr hvor langt frem appen henter, og hvordan gamle vagter håndteres.</div>
                                <div class="field">
                                    <label for="employment_type">Arbejdstype</label>
                                    <select id="employment_type" name="employment_type">
                                        <option value="ramme_ansat" {% if settings.employment_type == 'ramme_ansat' %}selected{% endif %}>Ramme ansat (sync hver time)</option>
                                        <option value="fast_turnus" {% if settings.employment_type == 'fast_turnus' %}selected{% endif %}>Fast turnus (sync tir+fre kl. 14)</option>
                                    </select>
                                </div>
                                <div class="field">
                                    <label for="days_ahead">Dage frem</label>
                                    <input id="days_ahead" name="days_ahead" type="number" min="1" max="365" value="{{ settings.days_ahead }}">
                                </div>
                                <div class="field">
                                    <label for="run_every_minutes">Kør hvert X minut</label>
                                    <input id="run_every_minutes" name="run_every_minutes" type="number" min="1" max="10080" value="{{ settings.run_every_minutes }}">
                                </div>
                                <label class="row"><input type="checkbox" name="remove_old_shifts" value="true" {% if settings.remove_old_shifts %}checked{% endif %}> Fjern gamle vagter ved sync</label>
                                <div class="field">
                                    <label for="calendar_public_base_url">Offentlig kalenderadresse</label>
                                    <input id="calendar_public_base_url" name="calendar_public_base_url" value="{{ settings.calendar_public_base_url or '' }}" placeholder="https://kalender.example.dk">
                                    <div class="field-hint">Lad feltet være tomt for kun at bruge kalenderen på lokalnetværket.</div>
                                </div>
                            </div>
                            <div class="section span-2">
                                <h2>Google Calendar</h2>
                                <div class="small">Log ind med din Google-konto og synkronisér de lokale vagter direkte til en Google Kalender.</div>
                                {% if not google_available %}
                                <div class="notice warning" style="margin-top:1rem; margin-bottom:0;">Google-afhængigheder mangler: {{ google_dependency_error }}</div>
                                {% endif %}
                                <div class="field">
                                    <label for="google_calendar_id">Google Calendar ID</label>
                                    <input id="google_calendar_id" name="google_calendar_id" value="{{ settings.google_calendar_id }}">
                                </div>
                                <div class="small" style="margin-top:0.9rem;">Status: {{ google_status.summary }}</div>
                                <div class="google-actions">
                                    <a class="ghost-button" href="{{ urls.google_connect_url }}">Log ind med Google</a>
                                    <form onsubmit="handleActionSubmit(event, '{{ urls.google_sync_url }}')">
                                        <button type="submit">Synkronisér til Google</button>
                                    </form>
                                    <form onsubmit="handleActionSubmit(event, '{{ urls.google_disconnect_url }}')">
                                        <button type="submit" class="ghost-button">Afbryd forbindelse</button>
                                    </form>
                                </div>
                                <details style="margin-top:1rem;">
                                    <summary style="cursor:pointer; font-weight:700;">Avanceret OAuth-opsætning</summary>
                                    <div class="field">
                                        <label for="google_client_id">OAuth Client ID</label>
                                        <input id="google_client_id" name="google_client_id" value="{{ settings.google_client_id }}">
                                    </div>
                                    <div class="field">
                                        <label for="google_client_secret">OAuth Client Secret</label>
                                        <input id="google_client_secret" name="google_client_secret" type="password" value="{{ settings.google_client_secret }}">
                                    </div>
                                    <div class="field">
                                        <label for="google_redirect_uri">Redirect URI</label>
                                        <input id="google_redirect_uri" name="google_redirect_uri" value="{{ settings.google_redirect_uri or google_status.redirect_uri }}">
                                    </div>
                                    <div class="small">Disse felter konfigureres én gang for RosterMate. Derefter bruger du kun “Log ind med Google”.</div>
                                </details>
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
        google_status=google_status,
        google_available=google_available,
        google_dependency_error=google_dependency_error,
        urls=urls,
        has_selfservice_session=has_selfservice_session,
        show_profile_switcher=show_profile_switcher,
    )


@app.route("/<driver_id>/settings", methods=["POST"])
def settings_route(driver_id: str) -> tuple[Any, int]:
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)

    employment_type = request.form.get("employment_type", settings.get("employment_type", "ramme_ansat"))
    if employment_type not in ("ramme_ansat", "fast_turnus"):
        employment_type = "ramme_ansat"

    remove_old_shifts = request.form.get("remove_old_shifts") == "true"
    updated_settings = {
        **settings,
        "url": request.form.get("url", settings.get("url", "")),
        "user": request.form.get("user", settings.get("user", "")),
        "pass": request.form.get("pass", settings.get("pass", "")),
        "days_ahead": int(request.form.get("days_ahead", settings.get("days_ahead", 7))),
        "run_every_minutes": int(request.form.get("run_every_minutes", settings.get("run_every_minutes", 60))),
        "remove_old_shifts": remove_old_shifts,
        "employment_type": employment_type,
        "google_client_id": request.form.get("google_client_id", settings.get("google_client_id", "")).strip(),
        "google_client_secret": request.form.get("google_client_secret", settings.get("google_client_secret", "")).strip(),
        "google_calendar_id": request.form.get("google_calendar_id", settings.get("google_calendar_id", "primary")).strip() or "primary",
        "google_redirect_uri": request.form.get("google_redirect_uri", settings.get("google_redirect_uri", "")).strip(),
        "calendar_public_base_url": request.form.get(
            "calendar_public_base_url", settings.get("calendar_public_base_url", "")
        ).strip().rstrip("/"),
    }
    save_driver_settings(safe_driver_id, updated_settings)
    return jsonify({"status": "ok", "message": "Indstillinger gemt", "employment_type": employment_type})


@app.route("/<driver_id>/google/connect")
def google_connect(driver_id: str) -> Any:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    google_status = google_integration_status(settings, safe_driver_id, paths["google_token_path"], request.url_root)
    if not google_status["client_id_valid"]:
        return redirect(
            url_for(
                "settings_page",
                driver_id=safe_driver_id,
                notice="OAuth Client ID er ugyldigt. Opret en Web application-klient i Google Cloud og indsæt det fulde ID, som slutter med .apps.googleusercontent.com.",
                notice_type="error",
            )
        )
    if not google_status["credentials_ready"]:
        return redirect(url_for("settings_page", driver_id=safe_driver_id, notice="Gem først Google Client ID og Client Secret", notice_type="warning"))

    google_available, dependency_error = google_dependencies_available()
    if not google_available:
        return redirect(url_for("settings_page", driver_id=safe_driver_id, notice=f"Google-afhængigheder mangler: {dependency_error}", notice_type="error"))

    flow = create_google_flow(settings, safe_driver_id, request.url_root)
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["google_oauth_state"] = state
    session["google_oauth_driver_id"] = safe_driver_id
    return redirect(authorization_url)


@app.route("/<driver_id>/google/callback")
def google_callback(driver_id: str) -> Any:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    google_available, dependency_error = google_dependencies_available()
    if not google_available:
        return redirect(url_for("settings_page", driver_id=safe_driver_id, notice=f"Google-afhængigheder mangler: {dependency_error}", notice_type="error"))

    state = session.get("google_oauth_state")
    oauth_driver_id = session.get("google_oauth_driver_id")
    if not state or oauth_driver_id != safe_driver_id:
        return redirect(url_for("settings_page", driver_id=safe_driver_id, notice="OAuth-sessionen mangler. Start login igen.", notice_type="warning"))

    try:
        flow = create_google_flow(settings, safe_driver_id, request.url_root, state)
        flow.fetch_token(authorization_response=request.url)
        save_google_token(paths["google_token_path"], flow.credentials)
    except Exception as exc:
        return redirect(url_for("settings_page", driver_id=safe_driver_id, notice=f"Google-login fejlede: {exc}", notice_type="error"))

    history = load_history(paths["history_path"])
    history.append({"timestamp": datetime.now().isoformat(), "summary": "Forbandt Google Calendar", "changes": []})
    save_history(history, paths["history_path"])
    session.pop("google_oauth_state", None)
    session.pop("google_oauth_driver_id", None)
    return redirect(url_for("settings_page", driver_id=safe_driver_id, notice="Google Calendar er nu forbundet", notice_type="success"))


@app.route("/<driver_id>/google/sync", methods=["POST"])
def google_sync(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    safe_driver_id = normalize_driver_id(driver_id)
    settings = load_settings(safe_driver_id)
    google_status = google_integration_status(settings, safe_driver_id, paths["google_token_path"])
    if not google_status["credentials_ready"]:
        return jsonify({"status": "error", "message": "Google OAuth credentials mangler i indstillinger"}), 400

    google_available, dependency_error = google_dependencies_available()
    if not google_available:
        return jsonify({"status": "error", "message": f"Google-afhængigheder mangler: {dependency_error}"}), 400

    events = load_json(paths["events_store_path"], [])
    if not events:
        return jsonify({"status": "error", "message": "Ingen lokale kalenderposter at synkronisere"}), 400

    try:
        result = sync_google_calendar_events(events, settings, paths["google_token_path"], paths["google_sync_state_path"])
    except Exception as exc:
        return jsonify({"status": "error", "message": f"Google-sync fejlede: {exc}"}), 400

    history = load_history(paths["history_path"])
    history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "summary": f"Google-sync: {result['inserted']} nye, {result['updated']} opdaterede, {result['deleted']} slettede",
            "changes": [],
        }
    )
    save_history(history, paths["history_path"])
    return jsonify({
        "status": "ok",
        "message": f"Google Calendar opdateret: {result['inserted']} nye, {result['updated']} opdaterede, {result['deleted']} slettede",
        "result": result,
    })


@app.route("/<driver_id>/google/disconnect", methods=["POST"])
def google_disconnect(driver_id: str) -> tuple[Any, int]:
    paths = get_driver_paths(driver_id)
    if paths["google_token_path"].exists():
        paths["google_token_path"].unlink()
    if paths["google_sync_state_path"].exists():
        paths["google_sync_state_path"].unlink()

    history = load_history(paths["history_path"])
    history.append({"timestamp": datetime.now().isoformat(), "summary": "Afbryd Google Calendar-forbindelse", "changes": []})
    save_history(history, paths["history_path"])
    return jsonify({"status": "ok", "message": "Google Calendar-forbindelsen er fjernet"})


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
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host=os.environ.get("ROSTERMATE_HOST", "0.0.0.0"), port=8080, debug=False, use_reloader=False)
