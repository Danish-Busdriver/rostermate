from datetime import date

import app as app_module
import hours


def shift(day: str, tid: str = "8h00", normal: str = "8h00", title: str = "DO_afløs") -> dict:
    return {
        "id": f"{day}:{title}", "title": title, "date": day,
        "start": f"{day}T06:00:00", "end": f"{day}T14:00:00", "all_day": False,
        "raw": f"ID: {title} Fra: 6:00 Til: 14:00 Tid: {tid} Normal tid: {normal} A",
    }


def day_off(day: str) -> dict:
    return {"id": "Fri", "title": "Fri", "date": day, "start": f"{day}T00:00:00",
            "end": f"{day}T23:59:59", "all_day": True, "raw": "Fri Normal tid: 0h00 A"}


def test_shift_minutes_reads_tid_and_normal_tid():
    assert hours.shift_minutes(shift("2026-12-01", "12h00", "10h00")) == (720, 600)
    assert hours.shift_minutes(day_off("2026-12-02")) == (0, 0)
    no_text = {**shift("2026-12-03"), "raw": ""}
    assert hours.shift_minutes(no_text) == (480, 480)  # falder tilbage til start/slut


def test_hours_overview_sums_week_and_month_with_difference():
    events = [shift("2026-11-23", "12h00", "10h00"), shift("2026-11-24"), day_off("2026-11-25"),
              shift("2026-11-30", "7h00", "8h00")]
    rows = {row["label"]: row for row in hours.hours_overview(events, today=date(2026, 11, 27))}
    assert rows["Denne uge"]["total"] == "20t 00m"
    assert rows["Denne uge"]["diff_label"] == "+2t 00m over normal"
    assert rows["Næste uge"]["diff_label"] == "−1t 00m under normal"
    assert rows["Denne måned"]["period"] == "november" and rows["Denne måned"]["total"] == "27t 00m"
    assert rows["Næste måned"]["total"] == "0t 00m"


def test_seven_work_days_in_a_row_is_a_streak_but_six_is_not():
    six = [shift(f"2026-12-0{d}") for d in range(1, 7)]
    assert hours.work_streaks(six) == []
    seven = six + [shift("2026-12-07")]
    assert hours.work_streaks(seven) == [(date(2026, 12, 1), date(2026, 12, 7), 7)]
    broken = six + [day_off("2026-12-07"), shift("2026-12-08")]
    assert hours.work_streaks(broken) == []
    assert hours.streak_warnings(seven, today=date(2026, 12, 8)) == []  # overstået stræk advares ikke


def test_flagged_shifts_follow_employment_type():
    early = shift("2026-12-10", "9h00", "8h00", "A")
    late = shift("2026-12-11", "9h00", "8h00", "B")
    history = [
        {"timestamp": "2026-12-01T10:00:00", "summary": "First run sync: 2", "changes": [
            {"type": "added", "item": early}, {"type": "added", "item": late}]},
        {"timestamp": "2026-12-09T08:00:00", "summary": "Automatisk sync", "changes": [{"type": "changed", "old": early, "new": early}]},
        {"timestamp": "2026-12-10T12:30:00", "summary": "Automatisk sync", "changes": [{"type": "changed", "old": late, "new": late}]},
    ]
    events = [early, late, shift("2026-12-12")]
    assert hours.flagged_shifts(events, "fast_turnus", history) == {("2026-12-10", "A"), ("2026-12-11", "B")}
    assert hours.flagged_shifts(events, "ramme_ansat", history) == {("2026-12-11", "B")}
    assert hours.flagged_shifts(events, "timeloennet", history) == set()


def test_change_that_creates_long_streak_sends_warning(monkeypatch):
    desktop, pushed = [], []
    monkeypatch.setattr(app_module, "send_change_notification", lambda _changes: True)
    monkeypatch.setattr(app_module, "send_desktop_notification", lambda message: desktop.append(message) or True)
    monkeypatch.setattr(app_module, "send_push_notification", lambda topic, message: pushed.append(message) or True)
    events = [shift(f"2026-12-0{d}") for d in range(1, 8)]

    app_module.notify_if_schedule_changed(
        {"push_enabled": True, "push_topic": "t"}, [{"type": "added", "item": events[-1]}],
        had_existing_events=True, events=events,
    )
    assert desktop == ["7 arbejdsdage i træk (01.12–07.12). Maks er 6."]
    assert "over 6 arbejdsdage i træk" in pushed[-1] and "12" not in pushed[-1]  # ingen datoer i offentlig push

    desktop.clear()
    app_module.notify_if_schedule_changed(
        {}, [{"type": "added", "item": shift("2026-12-20")}], had_existing_events=True, events=events,
    )
    assert desktop == []  # ændring uden for strækket gentager ikke advarslen
