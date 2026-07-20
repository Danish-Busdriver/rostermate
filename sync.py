from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable


def build_sync_preview(events: list[dict[str, Any]], limit_days: int = 3) -> list[dict[str, Any]]:
    weekday_names = ["Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag", "Søndag"]
    grouped: list[dict[str, Any]] = []
    seen_dates: set[str] = set()

    for event in sorted(events, key=lambda item: (item.get("date", ""), item.get("start", ""))):
        shift_date = str(event.get("date", "")).strip()
        if not shift_date:
            continue

        if shift_date not in seen_dates:
            if len(grouped) >= limit_days:
                continue
            try:
                shift_dt = date.fromisoformat(shift_date)
                weekday = weekday_names[shift_dt.weekday()]
            except ValueError:
                weekday = shift_date
            seen_dates.add(shift_date)
            grouped.append({"weekday": weekday, "items": []})

        target = grouped[-1]
        title = str(event.get("title", "Ukendt"))
        if "ID:" in title:
            title = title.split("ID:", 1)[1].strip()
        start = str(event.get("start", ""))
        end = str(event.get("end", ""))
        if event.get("all_day"):
            time_label = "Hele dagen"
        else:
            start_time = start.split("T", 1)[1][:5] if "T" in start else ""
            end_time = end.split("T", 1)[1][:5] if "T" in end else ""
            time_label = f"{start_time} - {end_time}".strip(" -") or "Tid ukendt"
        target["items"].append({"title": title, "time_label": time_label})

    return grouped


def run_initial_sync(
    driver_id: str,
    settings: dict[str, Any],
    paths: dict[str, Any],
    fetch_schedule: Callable[[int, str], tuple[list[dict[str, Any]], str]],
    sync_schedule: Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    write_outputs: Callable[[list[dict[str, Any]], list[dict[str, Any]], Any], None],
    load_json: Callable[[Any, Any], Any],
    load_history: Callable[[Any], list[dict[str, Any]]],
    save_history: Callable[[list[dict[str, Any]], Any], None],
) -> dict[str, Any]:
    days_ahead = int(settings.get("days_ahead", 7))
    existing_events = load_json(paths["events_store_path"], [])
    new_events, status_message = fetch_schedule(days_ahead, driver_id)

    if not new_events and not existing_events:
        raise RuntimeError(status_message)

    window_start = date.today().strftime("%Y-%m-%d")
    window_end = (date.today() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    updated_events, changes = sync_schedule(
        existing_events,
        new_events,
        window_start,
        window_end,
        bool(settings.get("remove_old_shifts", False)),
        paths["output_dir"],
    )
    write_outputs(updated_events, changes, paths["output_dir"])

    history = load_history(paths["history_path"])
    history.append(
        {
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "summary": f"First run sync: {len(new_events)} vagter hentet",
            "changes": changes,
        }
    )
    save_history(history, paths["history_path"])

    return {
        "events": updated_events,
        "changes": changes,
        "count": len(updated_events),
        "message": status_message,
        "preview": build_sync_preview(updated_events),
    }
