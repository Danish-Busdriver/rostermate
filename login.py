from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from session_store import SelfServiceSessionStore


TRANSIENT_NAVIGATION_ERRORS = (
    "navigating and changing the content",
    "execution context was destroyed",
)

LOGIN_FIELD_SELECTOR = "input#Username:visible, input#Password:visible"
AUTHENTICATED_MARKER_SELECTOR = (
    "#Calendar:visible, #NextMonth:visible, "
    "input[type='checkbox'][id*='View']:visible"
)


def read_stable_page_content(page: Any, attempts: int = 8) -> str | None:
    """Read page HTML without failing while an SSO redirect is in progress."""
    for _ in range(max(1, attempts)):
        try:
            return page.content()
        except Exception as exc:
            if not any(message in str(exc).lower() for message in TRANSIENT_NAVIGATION_ERRORS):
                raise
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                page.wait_for_timeout(250)
    return None


def detect_selfservice_login_state(page: Any) -> str:
    """Detect login state without reading or serializing the complete page."""
    try:
        if page.locator(LOGIN_FIELD_SELECTOR).count() > 0:
            return "login"
        if page.locator(AUTHENTICATED_MARKER_SELECTOR).count() > 0:
            return "authenticated"
        return "unknown"
    except Exception as exc:
        if any(message in str(exc).lower() for message in TRANSIENT_NAVIGATION_ERRORS):
            return "unknown"
        raise


def prefill_selfservice_credentials(page: Any, username: str, password: str) -> None:
    """Fill the visible login form without submitting it automatically."""
    if not username or not password or detect_selfservice_login_state(page) != "login":
        return
    page.locator("input#Username:visible").first.fill(username)
    page.locator("input#Password:visible").first.fill(password)


def launch_authenticated_context(
    playwright: Any,
    session_store: SelfServiceSessionStore,
    *,
    headless: bool,
    hide_window: bool = False,
) -> tuple[Any | None, Any]:
    """Reuse the persistent driver profile that completed the interactive login."""
    launch_options: dict[str, Any] = {"headless": headless}
    if hide_window and not headless:
        launch_options["args"] = [
            "--window-position=-32000,-32000",
            "--start-minimized",
        ]
    if session_store.user_data_dir.exists():
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(session_store.user_data_dir),
            **launch_options,
        )
        restore_saved_cookies(context, session_store)
        restore_session_storage(context, session_store)
        return None, context

    browser = playwright.chromium.launch(**launch_options)
    context_options: dict[str, Any] = {}
    if session_store.has_saved_session():
        context_options["storage_state"] = str(session_store.storage_state_path)
    context = browser.new_context(**context_options)
    restore_session_storage(context, session_store)
    return browser, context


def restore_saved_cookies(context: Any, session_store: SelfServiceSessionStore) -> None:
    """Restore session cookies that Chromium drops when the login window closes."""
    path = session_store.storage_state_path
    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    cookies = payload.get("cookies", []) if isinstance(payload, dict) else []
    if isinstance(cookies, list) and cookies:
        context.add_cookies(cookies)


def save_session_storage(page: Any, session_store: SelfServiceSessionStore) -> None:
    payload = page.evaluate(
        """() => ({
            origin: window.location.origin,
            items: Object.fromEntries(Object.entries(window.sessionStorage))
        })"""
    )
    if not isinstance(payload, dict) or not payload.get("origin") or not isinstance(payload.get("items"), dict):
        return
    path = session_store.session_storage_state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def restore_session_storage(context: Any, session_store: SelfServiceSessionStore) -> None:
    path = session_store.session_storage_state_path
    if not path.exists() or path.stat().st_size == 0:
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict) or not payload.get("origin") or not isinstance(payload.get("items"), dict):
        return
    serialized = json.dumps(payload).replace("</", "<\\/")
    context.add_init_script(
        script=f"""(() => {{
            const saved = {serialized};
            if (window.location.origin === saved.origin) {{
                for (const [key, value] of Object.entries(saved.items)) {{
                    window.sessionStorage.setItem(key, value);
                }}
            }}
        }})();"""
    )


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

    def start(
        self,
        driver_id: str,
        login_url: str,
        session_store: SelfServiceSessionStore,
        initial_sync: Callable[[Any], Any] | None = None,
        credentials: tuple[str, str] | None = None,
    ) -> LoginFlowState:
        flow_id = uuid.uuid4().hex
        state = LoginFlowState(flow_id=flow_id, driver_id=driver_id, state="launching", message="Åbner SelfService-login…")
        with self._lock:
            self._flows[flow_id] = state

        thread = threading.Thread(
            target=self._run_flow,
            args=(flow_id, login_url, session_store, initial_sync),
            kwargs={"credentials": credentials},
            daemon=True,
        )
        thread.start()
        return state

    def start_background(self, driver_id: str) -> LoginFlowState:
        flow_id = uuid.uuid4().hex
        state = LoginFlowState(
            flow_id=flow_id,
            driver_id=driver_id,
            state="connected",
            message="Loginoplysninger gemt sikkert. Logger ind i baggrunden…",
        )
        with self._lock:
            self._flows[flow_id] = state
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
                browser, context = launch_authenticated_context(playwright, session_store, headless=True)
                page = context.new_page()
                page.set_default_timeout(20000)
                page.goto(login_url, wait_until="domcontentloaded")
                login_state = "unknown"
                for _ in range(20):
                    login_state = detect_selfservice_login_state(page)
                    if login_state != "unknown":
                        break
                    page.wait_for_timeout(250)
                context.close()
                if browser is not None:
                    browser.close()
                if login_state == "authenticated":
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

    def _run_flow(
        self,
        flow_id: str,
        login_url: str,
        session_store: SelfServiceSessionStore,
        initial_sync: Callable[[Any], Any] | None = None,
        credentials: tuple[str, str] | None = None,
    ) -> None:
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
                page.goto(login_url, wait_until="domcontentloaded")
                if credentials is not None:
                    prefill_selfservice_credentials(page, credentials[0], credentials[1])
                self.update(flow_id, state="awaiting_login", message="Venter på at du logger ind i SelfService…")

                deadline = time.time() + 900
                authenticated_streak = 0
                unknown_streak = 0
                assignments_opened = False
                while time.time() < deadline:
                    login_state = detect_selfservice_login_state(page)
                    if login_state == "authenticated":
                        authenticated_streak += 1
                        unknown_streak = 0
                    else:
                        authenticated_streak = 0
                        unknown_streak = unknown_streak + 1 if login_state == "unknown" else 0
                    if unknown_streak >= 20 and not assignments_opened:
                        assignments_opened = True
                        page.goto(
                            urljoin(login_url.rstrip("/") + "/", "Assignments"),
                            wait_until="domcontentloaded",
                        )
                    # Require a stable rendered calendar for 1.5 seconds. The
                    # Assignments URL can appear before Tide has persisted the
                    # authenticated browser session.
                    if authenticated_streak >= 3:
                        try:
                            page.wait_for_selector("#Loading", state="hidden", timeout=15000)
                        except Exception:
                            pass
                        save_session_storage(page, session_store)
                        context.storage_state(path=str(session_store.storage_state_path), indexed_db=True)
                        initial_result = None
                        if initial_sync is not None:
                            # Fetch the first calendar directly in the browser
                            # that the user just authenticated. Tide rejects an
                            # immediate automated login in a second context.
                            self.update(flow_id, state="syncing", message="Henter dine vagter…")
                            initial_result = initial_sync(page)
                        context.close()
                        context = None
                        if isinstance(initial_result, dict) and initial_result.get("sync_complete"):
                            payload = initial_result
                            final_state = "synced"
                            final_message = str(initial_result.get("message", "Synkronisering gennemført"))
                        else:
                            payload = {"initial_fetch": initial_result} if initial_result is not None else {}
                            final_state = "connected"
                            final_message = "Forbundet til SelfService"
                        self.update(
                            flow_id,
                            state=final_state,
                            message=final_message,
                            payload=payload,
                        )
                        return
                    page.wait_for_timeout(500)

            self.update(flow_id, state="error", message="Login timed out. Prøv igen.")
        except Exception as exc:
            try:
                error_path = session_store.storage_state_path.parent / "wizard_error.log"
                error_path.parent.mkdir(parents=True, exist_ok=True)
                error_path.write_text(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} SelfService wizard error\n"
                    f"{traceback.format_exc()}",
                    encoding="utf-8",
                )
            except Exception:
                pass
            if "Target page, context or browser has been closed" in str(exc):
                message = "SelfService-vinduet blev lukket, før synkroniseringen var færdig. Prøv igen og lad vinduet lukke automatisk."
            else:
                message = f"Kunne ikke åbne SelfService-login: {exc}"
            self.update(flow_id, state="error", message=message)
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass


login_manager = SelfServiceLoginManager()
