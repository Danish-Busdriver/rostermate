from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from session import SelfServiceSessionStore


@dataclass
class LoginFlowState:
    flow_id: str
    driver_id: str
    state: str = "idle"
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)


class SelfServiceLoginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flows: dict[str, LoginFlowState] = {}

    def start(self, driver_id: str, login_url: str, session_store: SelfServiceSessionStore) -> LoginFlowState:
        flow_id = uuid.uuid4().hex
        state = LoginFlowState(flow_id=flow_id, driver_id=driver_id, state="launching", message="Åbner SelfService-login…")
        with self._lock:
            self._flows[flow_id] = state

        thread = threading.Thread(target=self._run_flow, args=(flow_id, login_url, session_store), daemon=True)
        thread.start()
        return state

    def get(self, flow_id: str) -> LoginFlowState | None:
        with self._lock:
            return self._flows.get(flow_id)

    def update(self, flow_id: str, *, state: str | None = None, message: str | None = None, payload: dict[str, Any] | None = None) -> LoginFlowState | None:
        with self._lock:
            item = self._flows.get(flow_id)
            if item is None:
                return None
            if state is not None:
                item.state = state
            if message is not None:
                item.message = message
            if payload is not None:
                item.payload = payload
            item.updated_at = time.time()
            return item

    def clear_driver_session(self, session_store: SelfServiceSessionStore) -> None:
        session_store.clear()

    def validate_saved_session(self, login_url: str, session_store: SelfServiceSessionStore) -> tuple[bool, str]:
        if not session_store.has_saved_session():
            return False, "Ingen gemt SelfService-session fundet. Forbind først til SelfService."

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            return False, f"Afhængighed mangler: {exc}"

        context = None
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(storage_state=str(session_store.storage_state_path))
                page = context.new_page()
                page.set_default_timeout(20000)
                page.goto(login_url, wait_until="load")
                html = page.content()
                logged_in = (
                    "Username" not in html
                    and "Password" not in html
                    and ("Assignments" in page.url or "Arbejdskalender" in html)
                )
                context.close()
                browser.close()
                if logged_in:
                    return True, "Forbindelsen virker. SelfService-sessionen er stadig gyldig."
                return False, "SelfService-sessionen ser ud til at være udløbet. Log ind igen via wizard-guiden."
        except Exception as exc:
            return False, f"Kunne ikke teste SelfService-forbindelsen: {exc}"
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

    def _run_flow(self, flow_id: str, login_url: str, session_store: SelfServiceSessionStore) -> None:
        context = None
        try:
            from playwright.sync_api import sync_playwright

            session_store.user_data_dir.mkdir(parents=True, exist_ok=True)
            self.update(flow_id, state="browser_open", message="Browser åbnet. Log ind på SelfService-vinduet.")

            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(session_store.user_data_dir),
                    headless=False,
                    viewport={"width": 1280, "height": 860},
                )
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(login_url, wait_until="load")
                self.update(flow_id, state="awaiting_login", message="Venter på at du logger ind i SelfService…")

                deadline = time.time() + 900
                while time.time() < deadline:
                    current_html = page.content()
                    logged_in = (
                        "Username" not in current_html
                        and "Password" not in current_html
                        and ("Assignments" in page.url or "Arbejdskalender" in current_html)
                    )
                    if logged_in:
                        context.storage_state(path=str(session_store.storage_state_path))
                        self.update(flow_id, state="connected", message="Forbundet til SelfService")
                        context.close()
                        return
                    page.wait_for_timeout(1000)

            self.update(flow_id, state="error", message="Login timed out. Prøv igen.")
        except Exception as exc:
            self.update(flow_id, state="error", message=f"Kunne ikke åbne SelfService-login: {exc}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass


login_manager = SelfServiceLoginManager()
