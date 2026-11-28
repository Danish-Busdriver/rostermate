"""Timer pr. uge og måned, afvigelser fra normal tid og maks 6 arbejdsdage i træk.

SelfService skriver fx "Tid: 12h00 Normal tid: 10h00" i vagtteksten (event["raw"]).
"Tid" er vagtens faktiske længde, "Normal tid" den oprindelige/normale.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

MAX_DAYS_IN_A_ROW = 6
MONTH_NAMES = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
               "august", "september", "oktober", "november", "december"]
_TID = re.compile(r"\bTid:\s*(\d+)h(\d+)")  # case-sensitivt, så "Normal tid:" ikke rammes
_NORMAL = re.compile(r"Normal tid:\s*(\d+)h(\d+)")


def _match_minutes(pattern: re.Pattern[str], raw: str) -> int | None:
    match = pattern.search(raw or "")
    return int(match[1]) * 60 + int(match[2]) if match else None


def _event_date(event: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(event.get("date", "")))
    except ValueError:
        return None


def is_work_shift(event: dict[str, Any]) -> bool:
    # Fri, Stregdag og ferie kommer som heldagsposter; alt med et klokkeslæt er arbejde.
    return not event.get("all_day")


def shift_minutes(event: dict[str, Any]) -> tuple[int, int]:
    """(faktiske minutter, normale minutter) for én post. Heldagsposter tæller 0."""
    if not is_work_shift(event):
        return 0, 0
    raw = str(event.get("raw", ""))
    actual = _match_minutes(_TID, raw)
    if actual is None:
        try:
            delta = datetime.fromisoformat(str(event["end"])) - datetime.fromisoformat(str(event["start"]))
            actual = max(0, int(delta.total_seconds() // 60))
        except (KeyError, ValueError):
            actual = 0
    normal = _match_minutes(_NORMAL, raw)
    return actual, actual if normal is None else normal


def _unique(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for event in events:
        key = str(event.get("id") or "") + "|" + str(event.get("date")) + "|" + str(event.get("start"))
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result


def sum_hours(events: Iterable[dict[str, Any]], start: date, end: date) -> tuple[int, int]:
    actual = normal = 0
    for event in _unique(events):
        day = _event_date(event)
        if day is not None and start <= day <= end:
            a, n = shift_minutes(event)
            actual += a
            normal += n
    return actual, normal


def format_minutes(minutes: int) -> str:
    return f"{minutes // 60}t {minutes % 60:02d}m"


def format_difference(minutes: int) -> tuple[str, str]:
    if minutes == 0:
        return "som normal tid", "hours-even"
    sign, label = ("+", "over") if minutes > 0 else ("−", "under")
    return f"{sign}{format_minutes(abs(minutes))} {label} normal", "hours-over" if minutes > 0 else "hours-under"


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    next_first = date(year + (month == 12), month % 12 + 1, 1)
    return first, next_first - timedelta(days=1)


def hours_overview(events: list[dict[str, Any]], today: date | None = None) -> list[dict[str, str]]:
    current = today or date.today()
    week_start = current - timedelta(days=current.weekday())
    next_month_year, next_month = (current.year + 1, 1) if current.month == 12 else (current.year, current.month + 1)
    periods = [
        ("Denne uge", f"uge {week_start.isocalendar().week}", week_start, week_start + timedelta(days=6)),
        ("Næste uge", f"uge {(week_start + timedelta(days=7)).isocalendar().week}",
         week_start + timedelta(days=7), week_start + timedelta(days=13)),
        ("Denne måned", MONTH_NAMES[current.month - 1], *_month_bounds(current.year, current.month)),
        ("Næste måned", MONTH_NAMES[next_month - 1], *_month_bounds(next_month_year, next_month)),
    ]
    rows = []
    for label, period, start, end in periods:
        actual, normal = sum_hours(events, start, end)
        diff_label, diff_class = format_difference(actual - normal)
        rows.append({"label": label, "period": period, "total": format_minutes(actual),
                     "diff_label": diff_label, "diff_class": diff_class})
    return rows


def work_streaks(events: list[dict[str, Any]], minimum: int = MAX_DAYS_IN_A_ROW + 1) -> list[tuple[date, date, int]]:
    """Sammenhængende arbejdsdage på mindst `minimum` dage: (første dag, sidste dag, antal)."""
    days = sorted({d for e in events if is_work_shift(e) and (d := _event_date(e)) is not None})
    streaks = []
    run_start = previous = None
    for day in days + [None]:
        if day is not None and previous is not None and day - previous == timedelta(days=1):
            previous = day
            continue
        if run_start is not None and previous is not None:
            length = (previous - run_start).days + 1
            if length >= minimum:
                streaks.append((run_start, previous, length))
        run_start = previous = day
    return streaks


def streak_warnings(events: list[dict[str, Any]], today: date | None = None) -> list[dict[str, Any]]:
    current = today or date.today()
    return [
        {"start": start.strftime("%d.%m"), "end": end.strftime("%d.%m"), "days": length}
        for start, end, length in work_streaks(events)
        if end >= current
    ]


def streaks_touching(events: list[dict[str, Any]], dates: set[str]) -> list[tuple[date, date, int]]:
    """Lange stræk, der indeholder mindst én af de givne datoer (fx datoer, der lige er ændret)."""
    touched = {date.fromisoformat(d) for d in dates if _valid_iso(d)}
    return [s for s in work_streaks(events) if any(s[0] <= d <= s[1] for d in touched)]


def _valid_iso(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def late_changed_shifts(history: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(dato, titel) for vagter, RosterMate så blive tilføjet/ændret efter kl. 12 dagen før vagten."""
    result: set[tuple[str, str]] = set()
    for entry in history:
        if str(entry.get("summary", "")).startswith("First run"):
            continue  # første hentning er ikke en ændring
        try:
            seen_at = datetime.fromisoformat(str(entry.get("timestamp", "")))
        except ValueError:
            continue
        for change in entry.get("changes") or []:
            item = change.get("new") if change.get("type") == "changed" else change.get("item")
            if change.get("type") not in ("added", "changed") or not isinstance(item, dict):
                continue
            day = _event_date(item)
            if day is not None and seen_at.replace(tzinfo=None) >= datetime.combine(day - timedelta(days=1), datetime.min.time()).replace(hour=12):
                result.add((day.isoformat(), str(item.get("title", ""))))
    return result


def flagged_shifts(
    events: list[dict[str, Any]],
    employment_type: str,
    history: list[dict[str, Any]],
) -> set[tuple[str, str]]:
    """Vagter med afvigende tid, der er relevante for ansættelsesformen.

    Fast turnus: alle afvigelser. Ramme ansat: kun når vagten blev ændret efter kl. 12 dagen før.
    """
    if employment_type not in ("fast_turnus", "ramme_ansat"):
        return set()
    late = late_changed_shifts(history) if employment_type == "ramme_ansat" else None
    flagged = set()
    for event in events:
        actual, normal = shift_minutes(event)
        key = (str(event.get("date", "")), str(event.get("title", "")))
        if actual != normal and (late is None or key in late):
            flagged.add(key)
    return flagged


def deviation_label(event: dict[str, Any]) -> str:
    actual, normal = shift_minutes(event)
    return f"Tid {format_minutes(actual)} · normal {format_minutes(normal)}"
