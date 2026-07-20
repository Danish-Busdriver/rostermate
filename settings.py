from __future__ import annotations

from typing import Any


def with_setup_defaults(settings: dict[str, Any]) -> dict[str, Any]:
    keep_old_shifts = not bool(settings.get("remove_old_shifts", False))
    return {
        **settings,
        "calendar_name": settings.get("calendar_name", "RosterMate"),
        "google_calendar_name": settings.get("google_calendar_name", "RosterMate"),
        "keep_old_shifts": settings.get("keep_old_shifts", keep_old_shifts),
        "launch_at_login": settings.get("launch_at_login", False),
        "show_menu_bar_icon": settings.get("show_menu_bar_icon", True),
        "notify_on_changes": settings.get("notify_on_changes", True),
        "wizard_completed": settings.get("wizard_completed", False),
    }


def apply_wizard_preferences(settings: dict[str, Any], form: dict[str, Any]) -> dict[str, Any]:
    keep_old_shifts = str(form.get("keep_old_shifts", "")).lower() in {"true", "1", "on", "yes"}
    return {
        **settings,
        "calendar_name": str(form.get("calendar_name", settings.get("calendar_name", "RosterMate"))).strip() or "RosterMate",
        "days_ahead": max(1, min(int(form.get("days_ahead", settings.get("days_ahead", 7))), 30)),
        "keep_old_shifts": keep_old_shifts,
        "remove_old_shifts": not keep_old_shifts,
        "launch_at_login": str(form.get("launch_at_login", "")).lower() in {"true", "1", "on", "yes"},
        "show_menu_bar_icon": str(form.get("show_menu_bar_icon", "")).lower() in {"true", "1", "on", "yes"},
        "notify_on_changes": str(form.get("notify_on_changes", "")).lower() in {"true", "1", "on", "yes"},
        "wizard_completed": True,
    }
