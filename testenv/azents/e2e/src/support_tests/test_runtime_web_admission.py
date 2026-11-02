"""Separate one real UI action's admission from metrics without a larger budget."""

from unittest.mock import Mock, PropertyMock

import pytest
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from selenium.common.exceptions import InvalidSessionIdException, TimeoutException

from tests.web.public import test_runtime_capability_web as web


def _runtime(generation: int, target: str) -> Mock:
    lifecycle = Mock(
        desired_generation=generation,
        target=target,
        convergence="converging",
        availability="pending",
    )
    return Mock(lifecycle=lifecycle)


def test_start_observes_new_running_generation_before_metrics_with_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock(current_window_handle="window")
    api = Mock(spec=AgentRuntimeV1Api)
    api.agent_runtime_v1_get_agent_runtime.side_effect = [
        _runtime(7, "stopped"),
        _runtime(7, "stopped"),
        _runtime(8, "running"),
    ]
    trace: list[str] = []
    click = Mock(side_effect=lambda *args: trace.append("click"))
    metrics = Mock(side_effect=lambda *args, **kwargs: trace.append("metrics"))
    wait = Mock()

    def until(predicate):
        trace.append("admission")
        assert predicate(driver) is False
        assert predicate(driver) is True
        return True

    wait.until.side_effect = until
    clock = Mock(side_effect=[100.0, 101.0, 102.0, 107.0])
    click_wait = Mock()
    click_wait.until.return_value = Mock(click=click)
    monkeypatch.setattr(web, "WebDriverWait", Mock(side_effect=[click_wait, wait]))
    monkeypatch.setattr(web, "_wait_for_runtime_metrics", metrics)
    monkeypatch.setattr(web.time, "monotonic", clock)
    web._start_runtime_and_wait_for_metrics(
        driver, runtime_api=api, token="token", handle="workspace", agent_id="agent"
    )
    assert trace == ["click", "admission", "metrics"]
    click.assert_called_once_with()
    metrics.assert_called_once_with(
        driver,
        runtime_api=api,
        token="token",
        handle="workspace",
        agent_id="agent",
        timeout_seconds=113.0,
    )


@pytest.mark.parametrize("generation,target", [(7, "running"), (8, "stopped")])
def test_unadmitted_start_fails_with_bounded_state_without_second_click_or_metrics(
    monkeypatch: pytest.MonkeyPatch, generation: int, target: str
) -> None:
    driver = Mock(current_window_handle="window")
    api = Mock(spec=AgentRuntimeV1Api)
    api.agent_runtime_v1_get_agent_runtime.side_effect = [
        _runtime(7, "stopped"),
        _runtime(generation, target),
    ]
    click, metrics, wait = Mock(), Mock(), Mock()

    def until(predicate):
        assert predicate(driver) is False
        raise TimeoutException("bounded admission")

    wait.until.side_effect = until
    click_wait = Mock()
    click_wait.until.return_value = Mock(click=click)
    monkeypatch.setattr(web, "WebDriverWait", Mock(side_effect=[click_wait, wait]))
    monkeypatch.setattr(web, "_wait_for_runtime_metrics", metrics)
    with pytest.raises(
        AssertionError, match="did not advance authoritative admission"
    ) as error:
        web._start_runtime_and_wait_for_metrics(
            driver,
            runtime_api=api,
            token="secret-token",
            handle="workspace",
            agent_id="agent",
        )
    assert "secret-token" not in str(error.value)
    assert f"generation={generation}, target={target}" in str(error.value)
    click.assert_called_once()
    metrics.assert_not_called()


def test_dead_browser_is_not_classified_as_metrics_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock()
    type(driver).current_window_handle = PropertyMock(
        side_effect=InvalidSessionIdException("browser retired")
    )
    api = Mock(spec=AgentRuntimeV1Api)
    wait = Mock()
    wait.until.side_effect = lambda predicate: predicate(driver)
    monkeypatch.setattr(web, "WebDriverWait", Mock(return_value=wait))
    with pytest.raises(InvalidSessionIdException, match="browser retired"):
        web._wait_for_runtime_metrics(
            driver,
            runtime_api=api,
            token="token",
            handle="workspace",
            agent_id="agent",
            timeout_seconds=120,
        )
    api.agent_runtime_v1_get_agent_runtime_system_metrics.assert_not_called()


def test_second_start_shares_one_budget_with_full_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock(current_window_handle="window")
    api = Mock(spec=AgentRuntimeV1Api)
    api.agent_runtime_v1_get_agent_runtime.side_effect = [
        _runtime(3, "stopped"),
        _runtime(4, "running"),
    ]
    click, wait = Mock(), Mock()
    wait.until.side_effect = lambda predicate: predicate(driver)
    click_wait = Mock()
    click_wait.until.return_value = Mock(click=click)
    monkeypatch.setattr(web, "WebDriverWait", Mock(side_effect=[click_wait, wait]))
    layout = Mock()
    monkeypatch.setattr(web, "_wait_for_settings_metrics_layout", layout)
    monkeypatch.setattr(
        web.time, "monotonic", Mock(side_effect=[100.0, 101.0, 102.0, 109.0])
    )
    remaining = web._start_runtime(
        driver,
        runtime_api=api,
        token="token",
        handle="workspace",
        agent_id="agent",
        wait_for_existing_metrics=True,
    )
    ready_wait = Mock()
    wait_factory = Mock(return_value=ready_wait)
    monkeypatch.setattr(web, "WebDriverWait", wait_factory)
    web._wait_for_runtime_ready(
        driver,
        runtime_api=api,
        token="token",
        handle="workspace",
        agent_id="agent",
        minimum_generation=4,
        timeout_seconds=remaining,
    )
    assert remaining == 111.0
    wait_factory.assert_called_once_with(driver, 111.0, poll_frequency=1)
    click.assert_called_once_with()
    layout.assert_called_once_with(driver, deadline=220.0)
    ready_wait.until.assert_called_once()


@pytest.mark.parametrize(
    "field,value",
    [
        ("desired_generation", 3),
        ("target", "stopped"),
        ("convergence", "converging"),
        ("availability", "pending"),
        ("provider", Mock(resource="stopped")),
        ("runner", Mock(state="disconnected")),
        ("complete", None),
    ],
)
def test_full_readiness_keeps_every_lifecycle_boundary(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    lifecycle = Mock(
        desired_generation=value if field == "desired_generation" else 4,
        target=value if field == "target" else "running",
        convergence=value if field == "convergence" else "stable",
        availability=value if field == "availability" else "ready",
        provider=value if field == "provider" else Mock(resource="running"),
        runner=value if field == "runner" else Mock(state="ready"),
    )
    api = Mock(spec=AgentRuntimeV1Api)
    api.agent_runtime_v1_get_agent_runtime.return_value = Mock(lifecycle=lifecycle)
    driver = Mock(current_window_handle="window")
    wait = Mock()

    def until(predicate):
        assert predicate(driver) is (field == "complete")

    wait.until.side_effect = until
    monkeypatch.setattr(web, "WebDriverWait", Mock(return_value=wait))
    web._wait_for_runtime_ready(
        driver,
        runtime_api=api,
        token="token",
        handle="workspace",
        agent_id="agent",
        minimum_generation=4,
        timeout_seconds=111,
    )


@pytest.mark.parametrize("missing_lifecycle", [False, True])
def test_ready_timeout_reports_bounded_last_state_without_credentials(
    monkeypatch: pytest.MonkeyPatch, missing_lifecycle: bool
) -> None:
    driver = Mock(current_window_handle="window")
    runtime = _runtime(4, "running")
    runtime.lifecycle.provider.resource = "running"
    runtime.lifecycle.runner.state = "disconnected"
    api = Mock(spec=AgentRuntimeV1Api)
    api.agent_runtime_v1_get_agent_runtime.return_value = (
        Mock(lifecycle=None) if missing_lifecycle else runtime
    )
    wait = Mock()

    def until(predicate):
        assert predicate(driver) is False
        raise TimeoutException("bounded readiness")

    wait.until.side_effect = until
    monkeypatch.setattr(web, "WebDriverWait", Mock(return_value=wait))
    with pytest.raises(AssertionError, match="did not regain full readiness") as error:
        web._wait_for_runtime_ready(
            driver,
            runtime_api=api,
            token="secret-token",
            handle="workspace",
            agent_id="agent",
            minimum_generation=4,
            timeout_seconds=111,
        )
    assert "secret-token" not in str(error.value)
    assert "minimum_generation=4" in str(error.value)
    assert (
        "no lifecycle"
        if missing_lifecycle
        else "provider_resource=running, runner_state=disconnected"
    ) in str(error.value)


def test_dead_browser_is_not_classified_as_runtime_readiness_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock()
    type(driver).current_window_handle = PropertyMock(
        side_effect=InvalidSessionIdException("browser retired")
    )
    api = Mock(spec=AgentRuntimeV1Api)
    wait = Mock()
    wait.until.side_effect = lambda predicate: predicate(driver)
    monkeypatch.setattr(web, "WebDriverWait", Mock(return_value=wait))
    with pytest.raises(InvalidSessionIdException, match="browser retired"):
        web._wait_for_runtime_ready(
            driver,
            runtime_api=api,
            token="token",
            handle="workspace",
            agent_id="agent",
            minimum_generation=4,
            timeout_seconds=111,
        )
    api.agent_runtime_v1_get_agent_runtime.assert_not_called()
