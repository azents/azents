"""Model stream watchdog E2E coverage through public product paths."""

import dataclasses
import time
from collections.abc import Callable

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from websockets.sync.connection import Connection

from support.image_watchdog_observations import (
    ContentObservation,
    WatchdogActionObservation,
    WatchdogLiveObservation,
    decode_image_requests,
)
from support.observations import (
    FailedAttemptObservation,
    FailedRunObservation,
    HistoryEventObservation,
    RunMarkerObservation,
    SystemErrorObservation,
)
from support.utils import model_selection_from_first_candidate, unique
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    connect_chat,
    create_agent,
    failed_run_error_events,
    history_events,
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
_PROVIDER_STOP_PROMPT = "Provider retry stop"
_PROVIDER_COMPACTION_SEED = "Provider compaction failure seed"
_PROVIDER_COMPACTION_SEED_RESPONSE = "Provider compaction failure seed response."
_TITLE_PROMPT = "Watchdog session title timeout"
_TITLE_RESPONSE = "WATCHDOG_TITLE_RUN_COMPLETED"
_TITLE_PROVIDER_RETRY_PROMPT = "Provider title retry"
_TITLE_PROVIDER_RETRY_RESPONSE = "PROVIDER_TITLE_RUN_COMPLETED"
_TITLE_PROVIDER_RETRY_TITLE = "Provider title retry recovered"
_TITLE_OUTPUT_FALLBACK_PROMPT = "Structured title fallback"
_TITLE_OUTPUT_FALLBACK_RESPONSE = "TITLE_OUTPUT_FALLBACK_RUN_COMPLETED"
_TITLE_OUTPUT_FALLBACK_TITLE = "Structured title fallback recovered"


def _title_request_modes(proxy_url: str, prompt: str) -> list[str]:
    """Read typed output-format evidence from the synthetic provider journal."""
    response = requests.get(f"{proxy_url}/v1/_image_generation_requests", timeout=10)
    response.raise_for_status()
    modes: list[str] = []
    for request in decode_image_requests(response.json()):
        serialized = request.serialized()
        if (
            prompt not in serialized
            or "Create a brief title from the request" not in serialized
        ):
            continue
        text = request.text
        structured = (
            text is not None
            and text.format is not None
            and text.format.type == "json_schema"
        )
        modes.append("structured" if structured else "plain_text")
    return modes


def _wait_until(
    condition: Callable[[], bool],
    *,
    timeout: float,
    message: str | Callable[[], str],
) -> None:
    """Poll a product-visible condition until it succeeds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    if isinstance(message, str):
        raise TimeoutError(message)
    raise TimeoutError(message())


def _wait_for_idle_run_boundary(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 15,
) -> None:
    """Wait until the prior Run has crossed the authoritative idle boundary."""
    observed: dict[str, object] | None = None

    def run_is_idle() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        live = WatchdogLiveObservation.model_validate(observed)
        return live.run is None and live.session_run_state == "idle"

    _wait_until(
        run_is_idle,
        timeout=timeout,
        message=f"session did not reach idle Run boundary: {observed!r}",
    )


def _live_partial_contents(payload: dict[str, object]) -> list[str]:
    """Return content strings from the validated live partial-history projection."""
    live = WatchdogLiveObservation.model_validate(payload)
    contents: list[str] = []
    for event in live.partial_history.items:
        content = ContentObservation.model_validate(event.payload).content
        if isinstance(content, str):
            contents.append(content)
    return contents


def _live_event_ids_containing(payload: dict[str, object], marker: str) -> set[str]:
    """Return typed live event IDs whose selected content contains a marker."""
    live = WatchdogLiveObservation.model_validate(payload)
    return {
        event.id
        for event in live.partial_history.items
        if isinstance(
            content := ContentObservation.model_validate(event.payload).content, str
        )
        and marker in content
    }


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
        message=lambda: f"live content did not appear: {content!r}, {observed!r}",
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
        run_payload = WatchdogLiveObservation.model_validate(observed).run
        if run_payload is None:
            return False
        run = run_payload
        retry_payload = run.retry
        if retry_payload is None:
            return False
        retry = retry_payload
        count = retry.failed_attempt_count
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
        event_id = WatchdogActionObservation.model_validate(removed).event_id
        observed.append(event_id)
        if event_id in expected_event_ids:
            return removed
    raise TimeoutError(
        f"expected WebSocket live-event removal was not observed: {observed!r}"
    )


def _wait_for_ws_live_content(
    websocket: Connection,
    *,
    session_id: str,
    content: str,
    timeout: float = 10,
) -> set[str]:
    """Wait for a subscribed live-event upsert containing one content marker."""
    deadline = time.monotonic() + timeout
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            raw = websocket.recv(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            continue
        action = WatchdogActionObservation.model_validate_json(raw)
        observed.append(action.type)
        if action.type != "live_event_upserted":
            continue
        assert action.session_id == session_id
        event = action.event
        assert event is not None
        payload = ContentObservation.model_validate(event.payload)
        event_content = payload.content
        event_id = event.id
        if (
            isinstance(event_content, str)
            and content in event_content
            and isinstance(event_id, str)
        ):
            return {event_id}
    raise TimeoutError(
        f"live WebSocket content did not appear: {content!r}, {observed!r}"
    )


def _wait_for_ws_clean_retry(
    websocket: Connection,
    *,
    session_id: str,
    failed_event_ids: set[str],
    failed_attempt_count: int,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait until failed live output is removed before the retry is published."""
    deadline = time.monotonic() + timeout
    removed_event_ids: set[str] = set()
    observed: list[object] = []
    while time.monotonic() < deadline:
        try:
            raw = websocket.recv(timeout=max(0.1, deadline - time.monotonic()))
        except TimeoutError:
            continue
        action = WatchdogActionObservation.model_validate_json(raw)
        action_type = action.type
        observed.append(action_type)
        if action_type == "live_event_removed":
            assert action.session_id == session_id
            event_id = action.event_id
            if isinstance(event_id, str):
                removed_event_ids.add(event_id)
            continue
        if action_type != "live_run_updated":
            continue
        assert action.session_id == session_id
        run = action.run
        assert run is not None
        retry = run.retry
        if retry is None or retry.failed_attempt_count != failed_attempt_count:
            continue
        assert failed_event_ids <= removed_event_ids
        return action.model_dump(mode="json", exclude_unset=True)
    raise TimeoutError(
        "clean WebSocket retry was not observed: "
        f"removed={removed_event_ids!r}, actions={observed!r}"
    )


def _failed_run_failure(payload: dict[str, object]) -> FailedRunObservation:
    """Return validated terminal failed-run metadata from selected history."""
    failed_events = failed_run_error_events(payload)
    assert len(failed_events) == 1, failed_events
    event = HistoryEventObservation.model_validate(failed_events[0])
    failure = SystemErrorObservation.model_validate(event.payload).failure
    assert failure is not None
    return failure


def _failed_attempts(payload: dict[str, object]) -> list[FailedAttemptObservation]:
    """Return validated terminal attempt evidence."""
    attempts = _failed_run_failure(payload).attempts
    assert attempts is not None
    return attempts


def _post_stop(*, public_url: str, token: str, session_id: str) -> None:
    """Stop one active Run through the public REST control boundary."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/stop",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={},
        timeout=10,
    )
    response.raise_for_status()


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


def _wait_for_live_provider_retry(
    *,
    public_url: str,
    token: str,
    session_id: str,
    failed_attempt_count: int,
    preparing_context: bool,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait for provider retry state and optional context-preparation operation."""
    observed: dict[str, object] | None = None

    def provider_retry_visible() -> bool:
        nonlocal observed
        observed = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        run_payload = WatchdogLiveObservation.model_validate(observed).run
        if run_payload is None:
            return False
        run = run_payload
        retry_payload = run.retry
        if retry_payload is None:
            return False
        retry = retry_payload
        observed_attempt_count = retry.failed_attempt_count
        if (
            retry.error_kind != "model_provider"
            or not isinstance(observed_attempt_count, int)
            or observed_attempt_count < failed_attempt_count
        ):
            return False
        attempts = retry.attempts
        if not attempts or any(
            attempt.retryability != "unknown" or attempt.failure_code is not None
            for attempt in attempts
        ):
            return False
        if not preparing_context:
            return True
        operation_payload = run.operation
        if operation_payload is None:
            return False
        operation = operation_payload
        return (
            operation.kind == "preparing_context"
            and operation.status == "running"
            and isinstance(operation.operation_id, str)
        )

    _wait_until(
        provider_retry_visible,
        timeout=timeout,
        message=f"live provider retry did not appear: {observed!r}",
    )
    assert observed is not None
    return observed


def _wait_for_stopped_without_failure(
    *,
    public_url: str,
    token: str,
    session_id: str,
    timeout: float = 15,
) -> dict[str, object]:
    """Wait for ordinary stopped history and complete live-state cleanup."""
    observed: dict[str, object] | None = None

    def stopped() -> bool:
        nonlocal observed
        observed = list_history(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        interrupted = False
        for raw_event in history_events(observed):
            event = HistoryEventObservation.model_validate(raw_event)
            if event.kind != "run_marker":
                continue
            event_payload = RunMarkerObservation.model_validate(event.payload)
            if event_payload.status == "interrupted":
                interrupted = True
                break
        if not interrupted or failed_run_error_events(observed):
            return False
        live = list_live(
            server_url=public_url,
            token=token,
            session_id=session_id,
        )
        return WatchdogLiveObservation.model_validate(live).run is None

    _wait_until(
        stopped,
        timeout=timeout,
        message=f"provider retry did not converge to terminal Stop: {observed!r}",
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
    email_input.send_keys(email)
    if not driver.find_elements(By.NAME, "password"):
        email_input.send_keys(Keys.ENTER)
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
            assert (
                WatchdogActionObservation.model_validate(subscribed).session_id
                == session_id
            )
            result = run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=session_id,
                message=_IDLE_PREFIX_PROMPT,
            )
            failed_event_ids = _wait_for_ws_live_content(
                websocket,
                session_id=session_id,
                content=_IDLE_FAILED_PREFIX,
            )
            retry_updated = _wait_for_ws_clean_retry(
                websocket,
                session_id=session_id,
                failed_event_ids=failed_event_ids,
                failed_attempt_count=1,
            )
            assert (
                WatchdogActionObservation.model_validate(retry_updated).session_id
                == session_id
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

    def run_absolute_cap_discards_failed_prefix_before_retry_and_browser_reload(
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
            assert (
                WatchdogActionObservation.model_validate(subscribed).session_id
                == session_id
            )
            result = run_message(
                public_api_client=public_api_client,
                public_url=azents_public_server_url,
                token=workspace.token,
                agent_id=agent_id,
                session_id=session_id,
                message=_ABSOLUTE_RECOVERY_PROMPT,
            )
            failed_event_ids = _wait_for_ws_live_content(
                websocket,
                session_id=result.session_id,
                content=_ABSOLUTE_FAILED_PREFIX,
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
            assert (
                WatchdogActionObservation.model_validate(removed).session_id
                == result.session_id
            )
            retry_updated = wait_for_ws_action(
                websocket,
                action_type="live_run_updated",
            )
            retry_run = WatchdogActionObservation.model_validate(retry_updated).run
            assert retry_run is not None
            retry = retry_run.retry
            assert retry is not None
            assert retry.failed_attempt_count == 1

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

    def test_user_stop_during_provider_retry_stays_terminal_and_non_replayable(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Stop during provider backoff creates no failed-run recovery state."""
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
            message=_PROVIDER_STOP_PROMPT,
        )
        _wait_for_live_provider_retry(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=1,
            preparing_context=False,
        )
        _post_stop(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        payload = _wait_for_stopped_without_failure(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )

        assert not system_error_events(payload)
        assert not failed_run_error_events(payload)

    def test_compaction_provider_failure_keeps_one_live_operation_until_exhaustion(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Provider compaction retries keep one operation and commit no summary."""
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
            message=_PROVIDER_COMPACTION_SEED,
        )
        wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_PROVIDER_COMPACTION_SEED_RESPONSE],
        )
        _wait_for_idle_run_boundary(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
        )
        _post_compact(
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            session_id=result.session_id,
        )
        first_live = _wait_for_live_provider_retry(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=1,
            preparing_context=True,
        )
        first_run = WatchdogLiveObservation.model_validate(first_live).run
        assert first_run is not None
        first_operation = first_run.operation
        assert first_operation is not None
        second_live = _wait_for_live_provider_retry(
            public_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            failed_attempt_count=2,
            preparing_context=True,
        )
        second_run = WatchdogLiveObservation.model_validate(second_live).run
        assert second_run is not None
        second_operation = second_run.operation
        assert second_operation is not None
        assert second_operation.operation_id == first_operation.operation_id

        payload = wait_for_failed_run_error(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected_attempts=4,
        )
        failure = _failed_run_failure(payload)
        attempts = _failed_attempts(payload)

        assert failure.error_kind == "model_provider"
        assert [attempt.attempt_number for attempt in attempts] == [1, 2, 3, 4]
        assert all(
            attempt.user_message.startswith("Model provider error:")
            for attempt in attempts
        )
        roles = message_roles(payload)
        assert "compaction_marker" not in roles
        assert "compaction_summary" not in roles

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
        session: AgentSessionResponse | None = None

        def initial_title_restored() -> bool:
            nonlocal session
            response = requests.get(
                f"{azents_public_server_url}/chat/v1/agents/{agent_id}"
                f"/sessions/{result.session_id}",
                headers=auth_headers(workspace.token),
                timeout=10,
            )
            response.raise_for_status()
            session = AgentSessionResponse.model_validate(response.json())
            return (
                session.title == _TITLE_PROMPT
                and session.title_source == "auto_initial"
            )

        _wait_until(
            initial_title_restored,
            timeout=15,
            message=lambda: f"Initial title was not restored: {session!r}",
        )
        assert session is not None
        assert session.title == _TITLE_PROMPT
        assert session.title_source == "auto_initial"

    def test_session_title_provider_failure_retries_without_failing_run(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Best-effort title generation retries provider failures independently."""
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
            message=_TITLE_PROVIDER_RETRY_PROMPT,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_TITLE_PROVIDER_RETRY_RESPONSE],
        )
        assert not system_error_events(payload)

        observed: AgentSessionResponse | None = None

        def title_recovered() -> bool:
            nonlocal observed
            response = requests.get(
                f"{azents_public_server_url}/chat/v1/agents/{agent_id}"
                f"/sessions/{result.session_id}",
                headers=auth_headers(workspace.token),
                timeout=10,
            )
            response.raise_for_status()
            observed = AgentSessionResponse.model_validate(response.json())
            return (
                observed.title == _TITLE_PROVIDER_RETRY_TITLE
                and observed.title_source == "auto_generated"
            )

        _wait_until(
            title_recovered,
            timeout=15,
            message=lambda: f"provider title retry did not recover: {observed!r}",
        )
        modes = _title_request_modes(openai_proxy_url, _TITLE_PROVIDER_RETRY_PROMPT)
        assert len(modes) == 2
        assert modes[0] == modes[1]

    def test_session_title_unsupported_schema_uses_plain_text(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Known absent schema support selects plain text from the first attempt."""
        del azents_engine_worker_container
        workspace = setup_workspace(
            public_api_client,
            admin_api_client,
            azents_public_server_url,
        )
        integration = LLMProviderIntegrationV1Api(
            public_api_client
        ).llm_provider_integration_v1_create_integration(
            handle=workspace.handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="__testenv_model_listing:deterministic-title-plain",
                secrets=Secrets(ApiKeySecrets(api_key="sk-title-plain-qa")),
            ),
            _headers=auth_headers(workspace.token),
        )
        selection = model_selection_from_first_candidate(
            azents_public_server_url,
            workspace.token,
            workspace.handle,
            integration.id,
        )
        assert selection.model_identifier == "gpt-5.5-title-plain"
        workspace = dataclasses.replace(workspace, model_selection=selection)
        agent_id = create_agent(public_api_client, workspace)
        result = run_message(
            public_api_client=public_api_client,
            public_url=azents_public_server_url,
            token=workspace.token,
            agent_id=agent_id,
            message=_TITLE_OUTPUT_FALLBACK_PROMPT,
        )
        payload = wait_for_rest_contents(
            server_url=azents_public_server_url,
            token=workspace.token,
            session_id=result.session_id,
            expected=[_TITLE_OUTPUT_FALLBACK_RESPONSE],
        )
        assert not system_error_events(payload)

        observed: AgentSessionResponse | None = None

        def title_recovered() -> bool:
            nonlocal observed
            response = requests.get(
                f"{azents_public_server_url}/chat/v1/agents/{agent_id}"
                f"/sessions/{result.session_id}",
                headers=auth_headers(workspace.token),
                timeout=10,
            )
            response.raise_for_status()
            observed = AgentSessionResponse.model_validate(response.json())
            return (
                observed.title == _TITLE_OUTPUT_FALLBACK_TITLE
                and observed.title_source == "auto_generated"
            )

        _wait_until(
            title_recovered,
            timeout=15,
            message=lambda: f"plain title output did not recover: {observed!r}",
        )
        assert _title_request_modes(
            openai_proxy_url, _TITLE_OUTPUT_FALLBACK_PROMPT
        ) == ["plain_text"]
