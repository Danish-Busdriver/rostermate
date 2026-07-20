from __future__ import annotations

from session import SelfServiceSessionStore


def should_show_first_run(settings: dict[str, object], session_store: SelfServiceSessionStore) -> bool:
    return not bool(settings.get("wizard_completed") and session_store.has_saved_session())


def should_show_welcome_back(settings: dict[str, object], session_store: SelfServiceSessionStore) -> bool:
    return bool(session_store.has_saved_session() and settings.get("wizard_completed"))
