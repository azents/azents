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
    clock = Mock(side_effect=[100.0, 107.0])
    monkeypatch.setattr(web, "_click_button", click)
    monkeypatch.setattr(web, "_wait", Mock(return_value=wait))
    monkeypatch.setattr(web, "_wait_for_runtime_metrics", metrics)
    monkeypatch.setattr(web.time, "monotonic", clock)
    web._start_runtime_and_wait_for_metrics(
        driver, runtime_api=api, token="token", handle="workspace", agent_id="agent"
    )
    assert trace == ["click", "admission", "metrics"]
    click.assert_called_once_with(driver, "Start")
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
    monkeypatch.setattr(web, "_click_button", click)
    monkeypatch.setattr(web, "_wait", Mock(return_value=wait))
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
