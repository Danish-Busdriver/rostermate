from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

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


def ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.touch(exist_ok=True)
    PLAN_PATH.touch(exist_ok=True)
    SETTINGS_PATH.touch(exist_ok=True)
    SCHEDULE_PATH.touch(exist_ok=True)
    EVENTS_STORE_PATH.touch(exist_ok=True)
    CHANGES_PATH.touch(exist_ok=True)
    ICS_PATH.touch(exist_ok=True)


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


def load_settings() -> dict[str, Any]:
    ensure_storage()
    env_values = {}
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_values[key.strip()] = value.strip().strip('"').strip("'")

    stored = load_json(SETTINGS_PATH, {})
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

    return {
        "url": env_values.get("SELFSERVICE_URL", stored.get("url", "https://selfservicedanmark.tidebus.dk")),
        "user": env_values.get("SELFSERVICE_USER", stored.get("user", "")),
        "pass": env_values.get("SELFSERVICE_PASS", stored.get("pass", "")),
        "days_ahead": max(1, min(days_ahead, 365)),
        "run_every_minutes": max(1, min(run_every_minutes, 10080)),
        "remove_old_shifts": _coerce_bool(env_values.get("REMOVE_OLD_SHIFTS", stored.get("remove_old_shifts", False))),
        "employment_type": employment_type,
    }


def save_settings(settings: dict[str, Any]) -> None:
    save_json(SETTINGS_PATH, settings)


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


def save_settings(settings: dict[str, Any]) -> None:
    save_json(SETTINGS_PATH, settings)


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
    is_all_day = any(token in shift_text for token in ["fri", "vacation", "stregdag"])

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


def write_outputs(events: list[dict[str, Any]], changes: list[dict[str, Any]], output_dir: Path | None = None) -> None:
    target_dir = output_dir or OUTPUT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    save_json(target_dir / "events_store.json", events)
    save_json(target_dir / "changes.json", changes)
    save_json(target_dir / "schedule.json", events)

    ics_lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RosterMate//EN"]
    for event in events:
        ics_lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.get('id', 'event')}",
                f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{event.get('start', '').replace('-', '').replace(':', '').replace('T', '')}",
                f"DTEND:{event.get('end', '').replace('-', '').replace(':', '').replace('T', '')}",
                f"SUMMARY:{event.get('title', 'Vagt')}",
                "END:VEVENT",
            ]
        )
    ics_lines.append("END:VCALENDAR")
    (target_dir / "vagter.ics").write_text("\n".join(ics_lines), encoding="utf-8")


def fetch_selfservice_schedule(days_ahead: int) -> tuple[list[dict[str, Any]], str]:
    settings = load_settings()
    if not settings.get("user") or not settings.get("pass"):
        return [], "Indtast brugernavn og adgangskode i .env"

    try:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return [], f"Afhængighed mangler: {exc}"

    html = None
    try:
        with sync_playwright() as p:
            # Start browser
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30000)
            
            # Navigér til login-siden
            page.goto(settings["url"], wait_until="load")
            
            # Log initial HTML for debugging
            initial_html = page.content()
            debug_path = OUTPUT_DIR / "debug_initial.log"
            with debug_path.open("w", encoding="utf-8") as f:
                f.write(initial_html[:10000])
            
            # Tjek om vi er på login-siden
            if "Username" in initial_html or "Password" in initial_html:
                # Udfyld login-form
                page.fill("input#Username", settings["user"])
                page.fill("input#Password", settings["pass"])
                
                # SelfService bruger en custom div for login-knappen
                # Prøv først #LoginButton, så fallback til andre muligheder
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
                    return [], "Kunne ikke finde login-knap"
                
                # Vent på at dashboard loader
                try:
                    page.wait_for_url("**/Assignments**", timeout=15000)
                except:
                    pass  # URL kan være anderledes
                
                # Vent på at loading-dialog forsvinder
                try:
                    page.wait_for_selector("#Loading", state="hidden", timeout=15000)
                except:
                    pass
                
                # Vent på at siden bliver idle
                page.wait_for_load_state("networkidle", timeout=20000)
            
            # Hent HTML efter at alt har ladet
            html = page.content()
            
            # DEBUG: Log HTML
            debug_path = OUTPUT_DIR / "debug_html.log"
            with debug_path.open("w", encoding="utf-8") as f:
                f.write(html[:50000])  # Øg til 50KB for bedre debugging
            
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
    shifts: list[dict[str, Any]] = []
    
    # SelfService bruger tider i formatet HH:MM
    # Søg efter alle elementer der indeholder denne pattern
    seen_time_pairs: set[str] = set()
    
    for elem in soup.find_all(True):
        text = elem.get_text(" ", strip=True)
        
        # Søg efter tid-mønstre (HH:MM)
        if re.search(r"\d{1,2}:\d{2}", text) and len(text) < 200:
            # Ekstrakt tider
            times = re.findall(r"(\d{1,2}:\d{2})", text)
            if times and len(times) >= 1:
                from_time = times[0]
                to_time = times[1] if len(times) > 1 else ""
                
                # Lav unik nøgle for at undgå duplikater
                time_pair = f"{from_time}-{to_time}"
                if time_pair not in seen_time_pairs:
                    seen_time_pairs.add(time_pair)
                    shift_title = text[:40] if text else f"{from_time} - {to_time}"
                    shifts.append({
                        "id": shift_title[:30],
                        "from": from_time,
                        "to": to_time,
                    })

    if not shifts:
        return [], "Ingen vagter fundet i kalenderen - muligvis ingen vagter planlagt"

    today = date.today()
    events: list[dict[str, Any]] = []
    for shift in shifts:
        for offset in range(days_ahead + 1):
            shift_date = (today + timedelta(days=offset)).strftime("%Y-%m-%d")
            events.append(build_event_from_shift(shift, shift_date))

    return events, f"Synkronisering gennemført - {len(shifts)} vagter hentet"


@app.route("/")
def index() -> str:
    ensure_storage()
    settings = load_settings()
    events = load_json(EVENTS_STORE_PATH, [])
    changes = load_json(CHANGES_PATH, [])
    last_sync = "Aldrig"
    if events:
        last_sync = datetime.now().strftime("%Y-%m-%d %H:%M")
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
                    --bg: #f3f6fb;
                    --panel: #ffffff;
                    --panel-2: #f8fbff;
                    --text: #14213d;
                    --muted: #6b7a90;
                    --accent: #2563eb;
                    --accent-2: #0f172a;
                    --border: #e6edf7;
                }
                * { box-sizing: border-box; }
                body {
                    margin: 0;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    background: linear-gradient(135deg, var(--bg) 0%, #eaf2ff 100%);
                    color: var(--text);
                }
                .container { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
                .hero {
                    background: linear-gradient(120deg, var(--accent-2) 0%, #1f4f8b 100%);
                    color: white;
                    border-radius: 24px;
                    padding: 1.5rem 1.6rem;
                    margin-bottom: 1rem;
                    box-shadow: 0 20px 40px rgba(15, 23, 42, 0.16);
                }
                .hero-top { display: flex; align-items: center; gap: 0.9rem; margin-bottom: 0.35rem; }
                .hero img { width: 52px; height: 52px; border-radius: 14px; background: white; padding: 0.2rem; }
                .hero h1 { margin: 0; font-size: 1.75rem; }
                .hero p { margin: 0; opacity: 0.9; }
                .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); }
                .card {
                    background: var(--panel);
                    border: 1px solid var(--border);
                    border-radius: 18px;
                    padding: 1.15rem 1.2rem;
                    box-shadow: 0 12px 28px rgba(15, 23, 42, 0.05);
                }
                .card h2 { margin: 0 0 0.6rem; font-size: 1rem; }
                .stat { font-size: 1.6rem; font-weight: 700; margin: 0.2rem 0; }
                .muted { color: var(--muted); }
                .pill { display: inline-block; padding: 0.25rem 0.6rem; border-radius: 999px; background: #eaf2ff; color: var(--accent); font-size: 0.8rem; font-weight: 600; }
                button, select, input { font: inherit; }
                button {
                    background: var(--accent);
                    color: white;
                    border: none;
                    border-radius: 999px;
                    padding: 0.7rem 1rem;
                    cursor: pointer;
                    font-weight: 600;
                }
                .list { list-style: none; padding: 0; margin: 0.5rem 0 0; }
                .list li {
                    padding: 0.6rem 0;
                    border-bottom: 1px solid var(--border);
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                }
                .list li:last-child { border-bottom: none; }
                .small { font-size: 0.9rem; color: var(--muted); }
                .row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
                .field { display: block; margin-top: 0.6rem; }
                .field select { margin-top: 0.25rem; width: 100%; padding: 0.6rem 0.75rem; border-radius: 10px; border: 1px solid var(--border); }
                .field label { font-size: 0.9rem; color: var(--muted); }
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
                <div class="hero">
                    <div class="hero-top">
                        <img src="/static/Rostermate.png" alt="RosterMate logo">
                        <h1>RosterMate</h1>
                    </div>
                    <p>Oversigt over vagter, ændringer og kommende synkroniseringer.</p>
                </div>
                <div class="grid">
                    <div class="card">
                        <span class="pill">Status</span>
                        <p class="stat">{{ status }}</p>
                        <p class="muted">Sidste sync: {{ last_sync }}</p>
                        <p class="muted">Næste sync: {{ next_sync }}</p>
                    </div>
                    <div class="card">
                        <span class="pill">Arbejdstype</span>
                        <p class="muted">{{ employment_type_label }}</p>
                        <p class="stat" style="font-size: 1.2rem;">{{ employment_type_display }}</p>
                    </div>
                    <div class="card">
                        <span class="pill">Kalenderposter</span>
                        <p class="stat">{{ event_count }}</p>
                        <p class="muted">Gemte poster i output</p>
                    </div>
                    <div class="card">
                        <span class="pill">Synkronisering</span>
                        <form onsubmit="handleFormSubmit(event, '/sync')">
                            <div class="field">
                                <label for="days_ahead">Dage frem</label>
                                <select name="days_ahead" id="days_ahead">
                                    {% for value in range(1, 31) %}
                                    <option value="{{ value }}" {% if value == days_ahead %}selected{% endif %}>{{ value }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <div style="margin-top:0.8rem;"><button type="submit">Synk nu</button></div>
                        </form>
                    </div>
                </div>
                <div class="grid" style="margin-top:1rem;">
                    <div class="card">
                        <h2>Næste vagter</h2>
                        <ul class="list">
                            {% for event in events[:7] %}
                            <li><span>{{ event.get('title', 'Ukendt') }}</span><span class="small">{{ event.get('date', '') }}</span></li>
                            {% else %}
                            <li>Ingen kalenderposter endnu.</li>
                            {% endfor %}
                        </ul>
                    </div>
                    <div class="card">
                        <h2>Ændringer</h2>
                        <ul class="list">
                            {% for change in changes[:5] %}
                            <li><span>{{ change.get('title', 'Ændring') }}</span><span class="small">{{ change.get('date', '') }}</span></li>
                            {% else %}
                            <li>Ingen ændringer endnu.</li>
                            {% endfor %}
                        </ul>
                    </div>
                    <div class="card">
                        <h2>Indstillinger</h2>
                        <form onsubmit="handleFormSubmit(event, '/settings')">
                            <div class="field">
                                <label for="employment_type">Arbejdstype</label>
                                <select name="employment_type" id="employment_type">
                                    <option value="ramme_ansat" {% if employment_type == 'ramme_ansat' %}selected{% endif %}>Ramme ansat (sync hver time)</option>
                                    <option value="fast_turnus" {% if employment_type == 'fast_turnus' %}selected{% endif %}>Fast turnus (sync tir+fre kl. 14)</option>
                                </select>
                            </div>
                            <label class="row"><input type="checkbox" name="remove_old_shifts" value="true" {% if remove_old_shifts %}checked{% endif %}> Fjern gamle vagter</label>
                            <div style="margin-top:0.8rem;"><button type="submit">Gem indstillinger</button></div>
                        </form>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """,
        status="Klar til sync",
        last_sync=last_sync,
        next_sync=calculate_next_sync(settings["employment_type"]),
        employment_type=settings["employment_type"],
        employment_type_label="Ansættelsesform",
        employment_type_display="Ramme ansat" if settings["employment_type"] == "ramme_ansat" else "Fast turnus",
        days_ahead=settings["days_ahead"],
        remove_old_shifts=settings["remove_old_shifts"],
        event_count=len(events),
        events=events,
        changes=changes,
    )


@app.route("/import", methods=["POST"])
def import_plan() -> tuple[Any, int]:
    ensure_storage()
    payload = request.form.get("plan_json", "[]")
    try:
        parsed_plan = json.loads(payload)
    except json.JSONDecodeError:
        return jsonify({"status": "error", "message": "Ugyldig JSON"}), 400

    if not isinstance(parsed_plan, list):
        return jsonify({"status": "error", "message": "Planen skal være en liste"}), 400

    old_plan = load_plan()
    changes = compare_plans(old_plan, parsed_plan)
    save_plan(parsed_plan)

    history = load_history()
    history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "summary": f"Importerede {len(parsed_plan)} vagter",
            "changes": changes,
        }
    )
    save_history(history)

    return jsonify({"status": "ok", "message": "Plan importeret", "changes": changes})


@app.route("/sync", methods=["POST"])
def sync_route() -> tuple[Any, int]:
    ensure_storage()
    settings = load_settings()
    days_ahead = int(request.form.get("days_ahead", settings.get("days_ahead", 7)))
    remove_old_shifts = request.form.get("remove_old_shifts") == "true"

    existing_events = load_json(EVENTS_STORE_PATH, [])
    new_events, status_message = fetch_selfservice_schedule(days_ahead)

    if not new_events and not existing_events:
        return jsonify({"status": "error", "message": status_message}), 400

    window_start = date.today().strftime("%Y-%m-%d")
    window_end = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    updated_events, changes = sync_schedule(existing_events, new_events, window_start, window_end, remove_old_shifts)
    write_outputs(updated_events, changes)

    history = load_history()
    history.append({"timestamp": datetime.now().isoformat(), "summary": f"Synkroniserede {len(new_events)} vagter", "changes": changes})
    save_history(history)
    save_settings({**settings, "days_ahead": days_ahead, "remove_old_shifts": remove_old_shifts})

    return jsonify({"status": "ok", "message": status_message, "events": updated_events, "changes": changes})


@app.route("/settings", methods=["POST"])
def settings_route() -> tuple[Any, int]:
    ensure_storage()
    settings = load_settings()

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
    }
    save_settings(updated_settings)
    return jsonify({"status": "ok", "message": "Indstillinger gemt", "employment_type": employment_type})


@app.route("/history")
def history_page() -> str:
    ensure_storage()
    history = load_history()
    return render_template_string(
        """
        <!doctype html>
        <html lang="da">
        <head>
            <meta charset="utf-8">
            <title>RosterMate Historik</title>
            <style>body{font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;margin:2rem;} .entry{margin-bottom:1rem;padding:1rem;border:1px solid #ddd;border-radius:12px;}</style>
        </head>
        <body>
            <h1>Historik</h1>
            <a href="/">Tilbage til dashboard</a>
            {% for entry in history %}
            <div class="entry">
                <strong>{{ entry.get('timestamp', '') }}</strong>
                <p>{{ entry.get('summary', '') }}</p>
                {% if entry.get('changes') %}
                <ul>
                    {% for change in entry['changes'] %}
                    <li>{{ change.get('type') }}: {{ change.get('id') }}</li>
                    {% endfor %}
                </ul>
                {% endif %}
            </div>
            {% else %}
            <p>Ingen historik endnu.</p>
            {% endfor %}
        </body>
        </html>
        """,
        history=history,
    )


@app.route("/backup", methods=["POST"])
def backup() -> tuple[Any, int]:
    ensure_storage()
    backup_path = create_backup(HISTORY_PATH)
    return jsonify({"status": "ok", "message": "Backup oprettet", "path": str(backup_path)})


@app.route("/health")
def health() -> tuple[Any, int]:
    ensure_storage()
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
