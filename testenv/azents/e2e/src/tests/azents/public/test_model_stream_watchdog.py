"""Model stream watchdog E2E coverage through public product paths."""

import time
from collections.abc import Callable

import azentsadminclient
import azentspublicclient
import pytest
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from websockets.sync.connection import Connection

from support.utils import unique
from tests.azents.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    create_agent,
    failed_run_error_events,
    history_events,
    json_object,
    json_object_list_payload,
    json_object_payload,
    list_history,
    list_live,
    message_contents,
    message_roles,
    run_message,
    setup_workspace,
    system_error_events,
    team_primary_session_id,
    wait_for_failed_run_error,
    wait_for_rest_contents,
    wait_for_ws_action,
)

_IDLE_RECOVERY_PROMPT = "Watchdog idle before first event then recover"
_IDLE_RECOVERY_RESPONSE = "WATCHDOG_IDLE_RECOVERED"
_IDLE_PREFIX_PROMPT = "Watchdog idle after prefix then recover"
_IDLE_FAILED_PREFIX = "FAILED_IDLE_PREFIX_MUST_DISAPPEAR"
_IDLE_PREFIX_RECOVERY_RESPONSE = "WATCHDOG_IDLE_PREFIX_RECOVERED"
_ABSOLUTE_RECOVERY_PROMPT = "Watchdog absolute cap cleans partial then recover"
_ABSOLUTE_FAILED_PREFIX = "FAILED_WATCHDOG_PREFIX_MUST_DISAPPEAR"
_ABSOLUTE_RECOVERY_RESPONSE = "WATCHDOG_ABSOLUTE_RECOVERED"
_EVENTS_RESET_PROMPT = "Watchdog parsed events reset idle"
_EVENTS_RESET_RESPONSE = (
    "WATCHDOG_EVENTS_RESET_IDLE abcdefghijklmnopqrstuvwxyz abcdefghijklmnopqrstuvwxyz"
)
_RETRY_EXHAUSTION_PROMPT = "Watchdog retry exhaustion"
_USER_STOP_PROMPT = "Watchdog user stop preserves partial"
_USER_STOP_PARTIAL = "WATCHDOG_STOP_PARTIAL"
_USER_STOP_RETRY_RESPONSE = "WATCHDOG_STOP_RETRY_RECOVERED"
_STOP_DISMISS_PROMPT = "Watchdog stop recovery dismissed by new message"
_STOP_DISMISS_PARTIAL = "WATCHDOG_DISMISS_STOP_PARTIAL"
_STOP_DISMISS_NEXT_PROMPT = "Watchdog new message after stop"
_STOP_DISMISS_NEXT_RESPONSE = "WATCHDOG_NEW_MESSAGE_AFTER_STOP_COMPLETED"
_COMPACTION_SEED = "Watchdog compaction timeout seed"
_COMPACTION_SEED_RESPONSE = "Watchdog compaction timeout seed response."
_TITLE_PROMPT = "Watchdog session title timeout"
_TITLE_RESPONSE = "WATCHDOG_TITLE_RUN_COMPLETED"


def _wait_until(
    condition: Callable[[], bool],
    *,
    timeout: float,
    message: str,
) -> None:
    """Poll a product-visible condition until it succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise TimeoutError(message)


def _live_partial_contents(payload: dict[str, object]) -> list[str]:
    """Return content strings from the REST live partial-history projection."""
    partial_history = json_object_payload(
        payload.get("partial_history"),
        label="live partial history",
    )
    events = json_object_list_payload(
        partial_history.get("items"),
        label="live partial history items",
    )
    contents: list[str] = []
    for event in events:
        event_payload = json_object_payload(
            event.get("payload"),
            label="live event payload",
        )
        content = event_payload.get("content")
        if isinstance(content, str):
            contents.append(content)
    return contents


def _live_event_ids_containing(
    payload: dict[str, object],
    marker: str,
) -> set[str]:
    """Return live event IDs whose projected content contains a marker."""
    partial_history = json_object_payload(
        payload.get("partial_history"),
        label="live partial history",
    )
    events = json_object_list_payload(
        partial_history.get("items"),
        label="live partial history items",
    )
    event_ids: set[str] = set()
    for event in events:
        event_payload = json_object_payload(
            event.get("payload"),
            label="live event payload",
        )
        content = event_payload.get("content")
        event_id = event.get("id")
        if isinstance(content, str) and marker in content and isinstance(event_id, str):
            event_ids.add(event_id)
    return event_ids


def _wait_for_live_content(
    *,
    public_url: str,
    token: str,
    session_id: str,
    content: str,
    timeout: float = 10,
) -> dict[str, object]:
    """Wait until one cumulative live model partial contains a marker."""
    observed: dict[str, object] | None = None

    def content_visible() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        return any(content in item for item in _live_partial_contents(observed))

    _wait_until(
        content_visible,
        timeout=timeout,
        message=f"live content did not appear: {content!r}, {observed!r}",
    )
    assert observed is not None
    return observed


def _wait_for_retry_without_content(
    *,
    public_url: str,
    token: str,
    session_id: str,
    failed_attempt_count: int,
    removed_content: str,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait for retry state whose live partials no longer contain failed output."""
    observed: dict[str, object] | None = None

    def retry_is_clean() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        run_payload = observed.get("run")
        if run_payload is None:
            return False
        run = json_object_payload(run_payload, label="live run")
        retry_payload = run.get("retry")
        if retry_payload is None:
            return False
        retry = json_object_payload(retry_payload, label="live run retry")
        count = retry.get("failed_attempt_count")
        return (
            isinstance(count, int)
            and count >= failed_attempt_count
            and all(
                removed_content not in content
                for content in _live_partial_contents(observed)
            )
        )

    _wait_until(
        retry_is_clean,
        timeout=timeout,
        message=f"clean retry state did not appear: {observed!r}",
    )
    assert observed is not None
    return observed


def _wait_for_ws_removed_event(
    websocket: Connection,
    *,
    expected_event_ids: set[str],
    timeout: float = 10,
) -> dict[str, object]:
    """Wait until WebSocket cleanup removes one expected live event."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        removed = wait_for_ws_action(
            websocket,
            action_type="live_event_removed",
            timeout=max(0.1, deadline - time.monotonic()),
        )
        event_id = removed.get("event_id")
        observed.append(event_id)
        if event_id in expected_event_ids:
            return removed
    raise TimeoutError(
        f"expected WebSocket live-event removal was not observed: {observed!r}"
    )


def _failed_attempts(payload: dict[str, object]) -> list[dict[str, object]]:
    """Return the terminal failed-run attempt history."""
    failed_events = failed_run_error_events(payload)
    assert len(failed_events) == 1, failed_events
    event_payload = json_object_payload(
        failed_events[0].get("payload"),
        label="failed-run event payload",
    )
    failure = json_object_payload(
        event_payload.get("failure"),
        label="failed-run failure",
    )
    return json_object_list_payload(
        failure.get("attempts"),
        label="failed-run attempts",
    )


def _run_marker_ids(payload: dict[str, object], *, status: str) -> set[str]:
    """Return Run IDs from durable markers with the requested status."""
    run_ids: set[str] = set()
    for event in history_events(payload):
        if event.get("kind") != "run_marker":
            continue
        marker = json_object_payload(
            event.get("payload"),
            label="run marker payload",
        )
        run_id = marker.get("run_id")
        if marker.get("status") == status and isinstance(run_id, str):
            run_ids.add(run_id)
    return run_ids


def _wait_for_completed_retry(
    *,
    public_url: str,
    token: str,
    session_id: str,
    stopped_run_id: str,
    expected_content: str,
    timeout: float = 90,
) -> dict[str, object]:
    """Wait until a different Run durably completes the stopped retry."""
    observed: dict[str, object] | None = None

    def retry_completed() -> bool:
        nonlocal observed
        observed = list_history(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        if expected_content not in message_contents(observed):
            return False
        return any(
            run_id != stopped_run_id
            for run_id in _run_marker_ids(observed, status="completed")
        )

    _wait_until(
        retry_completed,
        timeout=timeout,
        message=f"fresh retry Run did not complete: {observed!r}",
    )
    assert observed is not None
    return observed


def _post_stop(*, public_url: str, token: str, session_id: str) -> None:
    """Stop one active Run through the public REST control boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/stop",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={},
        timeout=10,
    )
    response.raise_for_status()


def _post_stopped_run_retry(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    stopped_run_id: str,
) -> dict[str, object]:
    """Retry one recoverable stopped Run through the public REST boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/retry-stopped-run",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "stopped_run_id": stopped_run_id,
            "client_request_id": f"watchdog-stopped-retry-{unique()}",
        },
        timeout=10,
    )
    response.raise_for_status()
    return json_object(response)


def _post_message_with_snapshot(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> dict[str, object]:
    """Post a user message and return its authoritative write snapshot."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"watchdog-message-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    return json_object(response)


def _post_compact(
    *,
    public_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Start manual compaction through the public command input boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"watchdog-compact-{unique()}",
            "message": "",
            "action": {"type": "command", "name": "compact"},
            "inference_profile": None,
        },
        timeout=10,
    )
    response.raise_for_status()


def _wait_for_interrupted_partial(
    *,
    public_url: str,
    token: str,
    session_id: str,
    content_marker: str,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait until User Stop durably retains the valid partial and interruption."""
    observed: dict[str, object] | None = None

    def interrupted() -> bool:
        nonlocal observed
        observed = list_history(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        if not any(content_marker in content for content in message_contents(observed)):
            return False
        for event in history_events(observed):
            if event.get("kind") != "run_marker":
                continue
            event_payload = json_object_payload(
                event.get("payload"),
                label="run marker payload",
            )
            if event_payload.get("status") == "interrupted":
                return True
        return False

    _wait_until(
        interrupted,
        timeout=timeout,
        message=f"interrupted partial did not become durable: {observed!r}",
    )
    assert observed is not None
    return observed


def _wait_for_stopped_recovery(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait until the live projection exposes one recoverable stopped Run."""
    observed: dict[str, object] | None = None

    def recovery_visible() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        run_payload = observed.get("run")
        if run_payload is None:
            return False
        run = json_object_payload(run_payload, label="recoverable stopped run")
        recovery_payload = run.get("recovery")
        if recovery_payload is None:
            return False
        recovery = json_object_payload(
            recovery_payload,
            label="stopped run recovery",
        )
        return recovery.get("source_run_id") == run.get("run_id")

    _wait_until(
        recovery_visible,
        timeout=timeout,
        message=f"stopped recovery did not appear: {observed!r}",
    )
    assert observed is not None
    return observed


def _wait_for_no_live_run(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait until no active or recoverable Run remains in the live projection."""
    observed: dict[str, object] | None = None

    def run_cleared() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        return observed.get("run") is None

    _wait_until(
        run_cleared,
        timeout=timeout,
        message=f"live run did not clear: {observed!r}",
    )
    assert observed is not None
    return observed


def _open_authenticated_raw_events(
    driver: WebDriver,
    *,
    main_web_url: str,
    email: str,
    workspace_handle: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Log in and open the real Main Web raw-events page."""
    driver.delete_all_cookies()
    driver.get(f"{main_web_url}/login")
    wait = WebDriverWait(driver, 30)
    email_input = wait.until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    wait.until(ec.url_contains("/login/password"))
    password_input = wait.until(ec.element_to_be_clickable((By.NAME, "password")))
    password_input.send_keys("TestPass123!", Keys.ENTER)
    wait.until(ec.url_contains("/workspaces"))
    driver.get(
        f"{main_web_url}/w/{workspace_handle}/agents/{agent_id}"
        f"/sessions/{session_id}?page=raw-events"
    )


class TestModelStreamWatchdog:
    """Validate timeout, retry, cleanup, Stop, and caller-specific behavior."""

    def test_idle_before_first_event_retries_without_durable_timeout(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """No parsed event enters failed-run retry and the next attempt recovers."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)

        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_IDLE_RECOVERY_PROMPT,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_IDLE_RECOVERY_PROMPT, _IDLE_RECOVERY_RESPONSE],
        )

        assert not system_error_events(payload)
        assert "This response must never become durable." not in message_contents(
            payload
        )

    def test_idle_after_visible_prefix_discards_partial_before_retry(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """An inter-event stall removes its visible prefix before retry recovery."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_IDLE_PREFIX_PROMPT,
        )
        _wait_for_live_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            content=_IDLE_FAILED_PREFIX,
        )
        _wait_for_retry_without_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=1,
            removed_content=_IDLE_FAILED_PREFIX,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_IDLE_PREFIX_RECOVERY_RESPONSE],
        )

        assert not system_error_events(payload)
        assert all(
            _IDLE_FAILED_PREFIX not in content for content in message_contents(payload)
        )

    @pytest.mark.web_surface
    def test_absolute_cap_discards_failed_prefix_before_retry_and_browser_reload(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        browser_driver: WebDriver,
        azents_main_web_url: str,
    ) -> None:
        """Absolute timeout removes live output before retry and all resync paths."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        session_id = team_primary_session_id(
            server_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
        )
        with connect_chat(
            public_api_client=public_api_client,
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=session_id,
        ) as websocket:
            subscribed = wait_for_ws_action(websocket, action_type="subscribed")
            assert subscribed.get("session_id") == session_id
            result = run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=session_id,
                message=_ABSOLUTE_RECOVERY_PROMPT,
            )
            live_payload = _wait_for_live_content(
                public_url=azents_public_server_url,
                token=workspace.token,
                session_id=result.session_id,
                content=_ABSOLUTE_FAILED_PREFIX,
            )
            failed_event_ids = _live_event_ids_containing(
                live_payload,
                _ABSOLUTE_FAILED_PREFIX,
            )
            assert failed_event_ids
            _wait_for_retry_without_content(
                public_url=azents_public_server_url,
                token=workspace.token,
                session_id=result.session_id,
                failed_attempt_count=1,
                removed_content=_ABSOLUTE_FAILED_PREFIX,
            )
            removed = _wait_for_ws_removed_event(
                websocket,
                expected_event_ids=failed_event_ids,
            )
            assert removed.get("session_id") == result.session_id
            retry_updated = wait_for_ws_action(
                websocket,
                action_type="live_run_updated",
            )
            retry_run = json_object_payload(
                retry_updated.get("run"),
                label="WebSocket live run",
            )
            retry = json_object_payload(
                retry_run.get("retry"),
                label="WebSocket retry state",
            )
            assert retry.get("failed_attempt_count") == 1

        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_ABSOLUTE_RECOVERY_RESPONSE],
        )
        assert not system_error_events(payload)
        assert all(
            _ABSOLUTE_FAILED_PREFIX not in content
            for content in message_contents(payload)
        )

        _open_authenticated_raw_events(
            browser_driver,
            main_web_url=azents_main_web_url,
            email=workspace.email,
            workspace_handle=workspace.handle,
            agent_id=agent_id,
            session_id=result.session_id,
        )
        browser_wait = WebDriverWait(browser_driver, 30)
        assistant_event = browser_wait.until(
            ec.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[.//*[normalize-space()='assistant_message']]",
                )
            )
        )
        assistant_event.click()
        browser_wait.until(
            lambda driver: _ABSOLUTE_RECOVERY_RESPONSE in driver.page_source
        )
        assert _ABSOLUTE_FAILED_PREFIX not in browser_driver.page_source

    def test_parsed_events_refresh_idle_until_stream_completion(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """A response longer than idle succeeds when every event gap stays short."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        started_at = time.monotonic()
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_EVENTS_RESET_PROMPT,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_EVENTS_RESET_RESPONSE],
        )

        assert time.monotonic() - started_at > 0.5
        assert not system_error_events(payload)

    def test_idle_timeout_retry_exhaustion_preserves_stable_failure_codes(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Only exhausted timeout failure is durable with all attempt codes."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_RETRY_EXHAUSTION_PROMPT,
        )
        payload = wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )

        attempts = _failed_attempts(payload)
        assert [attempt.get("attempt_number") for attempt in attempts] == [1, 2, 3, 4]
        assert {attempt.get("failure_code") for attempt in attempts} == {
            "model_stream_idle_timeout"
        }
        assert all(attempt.get("retryability") == "transient" for attempt in attempts)

    def test_user_stop_exposes_recovery_and_retry_starts_fresh_run(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Stop retains valid output and Retry starts a fresh recoverable Run."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_USER_STOP_PROMPT,
        )
        _wait_for_live_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            content=_USER_STOP_PARTIAL,
        )
        _post_stop(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        history = _wait_for_interrupted_partial(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            content_marker=_USER_STOP_PARTIAL,
        )
        live = _wait_for_stopped_recovery(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        stopped_run = json_object_payload(
            live.get("run"),
            label="recoverable stopped run",
        )
        stopped_run_id = stopped_run.get("run_id")
        assert isinstance(stopped_run_id, str)
        recovery = json_object_payload(
            stopped_run.get("recovery"),
            label="stopped run recovery",
        )
        assert recovery.get("kind") == "stopped"
        assert recovery.get("user_message") == "Execution stopped."
        assert recovery.get("operation") == "sampling"
        assert recovery.get("source_run_id") == stopped_run_id

        retry = _post_stopped_run_retry(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
            stopped_run_id=stopped_run_id,
        )
        accepted = json_object_payload(
            retry.get("accepted"),
            label="stopped retry accepted target",
        )
        assert accepted == {"type": "stopped_run_retry", "id": stopped_run_id}
        snapshot = json_object_payload(
            retry.get("snapshot"),
            label="stopped retry snapshot",
        )
        retry_run_payload = snapshot.get("run")
        if retry_run_payload is not None:
            retry_run = json_object_payload(
                retry_run_payload,
                label="fresh retry run",
            )
            assert retry_run.get("run_id") != stopped_run_id
            assert retry_run.get("retry") is None
            assert retry_run.get("recovery") is None

        final_history = _wait_for_completed_retry(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            stopped_run_id=stopped_run_id,
            expected_content=_USER_STOP_RETRY_RESPONSE,
        )
        assert not system_error_events(history)
        assert not system_error_events(final_history)
        assert "run_complete" in message_roles(history)
        assert any(
            _USER_STOP_PARTIAL in content for content in message_contents(final_history)
        )

    def test_new_message_dismisses_stopped_recovery_and_runs_normally(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """A new user message replaces an old stopped recovery projection."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_STOP_DISMISS_PROMPT,
        )
        _wait_for_live_content(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            content=_STOP_DISMISS_PARTIAL,
        )
        _post_stop(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        _wait_for_interrupted_partial(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            content_marker=_STOP_DISMISS_PARTIAL,
        )
        live = _wait_for_stopped_recovery(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        stopped_run = json_object_payload(
            live.get("run"),
            label="dismissed stopped run",
        )
        stopped_run_id = stopped_run.get("run_id")
        assert isinstance(stopped_run_id, str)

        write = _post_message_with_snapshot(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
            message=_STOP_DISMISS_NEXT_PROMPT,
        )
        accepted = json_object_payload(
            write.get("accepted"),
            label="new message accepted target",
        )
        assert accepted.get("type") == "input_buffer"
        snapshot = json_object_payload(
            write.get("snapshot"),
            label="new message snapshot",
        )
        new_run_payload = snapshot.get("run")
        if new_run_payload is None:
            pending_inputs = json_object_list_payload(
                snapshot.get("input_buffer_events"),
                label="new message input buffer",
            )
            assert pending_inputs
        else:
            new_run = json_object_payload(
                new_run_payload,
                label="new message run",
            )
            assert new_run.get("run_id") != stopped_run_id
            assert new_run.get("recovery") is None

        final_history = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_STOP_DISMISS_NEXT_PROMPT, _STOP_DISMISS_NEXT_RESPONSE],
        )
        assert not system_error_events(final_history)
        _wait_for_no_live_run(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )

    def test_compaction_timeout_uses_run_retry_and_commits_no_summary(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Blocking compaction timeouts fail the command without a partial summary."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_COMPACTION_SEED,
        )
        wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_COMPACTION_SEED_RESPONSE],
        )
        _post_compact(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
        )
        payload = wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )

        roles = message_roles(payload)
        assert "compaction_marker" not in roles
        assert "compaction_summary" not in roles
        assert len(failed_run_error_events(payload)) == 1
        assert {
            attempt.get("failure_code") for attempt in _failed_attempts(payload)
        } == {"model_stream_idle_timeout"}

    def test_session_title_timeout_does_not_fail_completed_run(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Best-effort title timeout leaves the successful agent Run intact."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_TITLE_PROMPT,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_TITLE_RESPONSE],
        )

        assert not system_error_events(payload)
        time.sleep(1)
        response = requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{agent_id}"
            f"/sessions/{result.session_id}",
            headers=auth_headers(workspace.token),
            timeout=10,
        )
        response.raise_for_status()
        session = json_object(response)
        assert session.get("title") == _TITLE_PROMPT
        assert session.get("title_source") == "auto_initial"
