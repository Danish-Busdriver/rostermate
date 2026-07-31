from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from typing import Any, Protocol


class RandomSource(Protocol):
    def randint(self, start: int, end: int) -> int: ...


SCHEDULE_KEY = "automatic_sync_times"
LAST_ATTEMPT_KEY = "last_automatic_sync_slot"
RAMME_KEY = "ramme_daily"
TUESDAY_KEY = "turnus_tuesday"
THURSDAY_KEY = "turnus_thursday"

WINDOWS = {
    RAMME_KEY: (-1, 12 * 60, 14 * 60),
    TUESDAY_KEY: (1, 9 * 60, 16 * 60),
    THURSDAY_KEY: (3, 9 * 60, 16 * 60),
}


def _format_minute(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def _parse_minute(value: Any) -> int | None:
    try:
        hour_text, minute_text = str(value).split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def ensure_automatic_sync_times(
    settings: dict[str, Any],
    rng: RandomSource | None = None,
) -> tuple[dict[str, Any], bool]:
    """Add stable random per-profile sync times without replacing valid choices."""
    source = rng or random.SystemRandom()
    existing = settings.get(SCHEDULE_KEY)
    times = dict(existing) if isinstance(existing, dict) else {}
    changed = not isinstance(existing, dict)

    for key, (_weekday, start_minute, end_minute) in WINDOWS.items():
        selected = _parse_minute(times.get(key))
        if selected is None or not start_minute <= selected < end_minute:
            times[key] = _format_minute(source.randint(start_minute, end_minute - 1))
            changed = True

    if not changed:
        return settings, False
    return {**settings, SCHEDULE_KEY: times}, True


def schedule_summary(settings: dict[str, Any]) -> str:
    times = settings.get(SCHEDULE_KEY, {})
    if settings.get("employment_type") == "fast_turnus":
        return f"Tirsdag kl. {times.get(TUESDAY_KEY, '--:--')} og torsdag kl. {times.get(THURSDAY_KEY, '--:--')}"
    return f"Dagligt kl. {times.get(RAMME_KEY, '--:--')}"


def _active_schedule(settings: dict[str, Any]) -> list[tuple[str, int, int, int]]:
    keys = [TUESDAY_KEY, THURSDAY_KEY] if settings.get("employment_type") == "fast_turnus" else [RAMME_KEY]
    result = []
    times = settings.get(SCHEDULE_KEY, {})
    for key in keys:
        weekday, start_minute, end_minute = WINDOWS[key]
        selected = _parse_minute(times.get(key))
        if selected is not None and start_minute <= selected < end_minute:
            result.append((key, weekday, selected, end_minute))
    return result


def automatic_sync_slot(settings: dict[str, Any], now: datetime) -> str | None:
    """Return the due slot once its selected minute is reached and while its window is open."""
    current_minute = now.hour * 60 + now.minute
    for key, weekday, selected, end_minute in _active_schedule(settings):
        if (weekday != -1 and now.weekday() != weekday) or not selected <= current_minute < end_minute:
            continue
        slot = f"{now.date().isoformat()}:{key}"
        if settings.get(LAST_ATTEMPT_KEY) != slot:
            return slot
    return None


def next_automatic_sync(settings: dict[str, Any], now: datetime) -> datetime | None:
    candidates: list[datetime] = []
    for days_ahead in range(8):
        day = now.date() + timedelta(days=days_ahead)
        for key, weekday, selected, _end_minute in _active_schedule(settings):
            if weekday != -1 and day.weekday() != weekday:
                continue
            candidate = datetime.combine(day, time(selected // 60, selected % 60), tzinfo=now.tzinfo)
            slot = f"{day.isoformat()}:{key}"
            if candidate > now and settings.get(LAST_ATTEMPT_KEY) != slot:
                candidates.append(candidate)
    return min(candidates) if candidates else None
