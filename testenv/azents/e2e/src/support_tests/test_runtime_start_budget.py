"""Runtime Start helper synchronization retains one click and one total budget."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from tests.web.public import test_runtime_capability_web as subject


@pytest.mark.parametrize("existing_metrics", [False, True])
@pytest.mark.parametrize(
    "clock,expected_waits,expected_remaining",
    [([100, 110, 115, 125], [20, 20], 95), ([100, 215, 217, 219], [5, 3], 1)],
)
def test_start_observes_existing_layout_before_one_click(
    existing_metrics: bool,
    clock: list[float],
    expected_waits: list[float],
    expected_remaining: float,
) -> None:
    driver = MagicMock(spec=WebDriver)
    api = MagicMock(spec=subject.AgentRuntimeV1Api)
    before = MagicMock()
    before.lifecycle.desired_generation = 3
    after = MagicMock()
    after.lifecycle.desired_generation = 4
    after.lifecycle.target = "running"
    api.agent_runtime_v1_get_agent_runtime.side_effect = [before, after]
    order: list[str] = []
    remaining_waits: list[float] = []
    button = MagicMock()
    button.click.side_effect = lambda: order.append("click")
    calls = 0

    def wait(_driver: WebDriver, timeout: float, **_kwargs: object) -> MagicMock:
        nonlocal calls
        remaining_waits.append(timeout)
        result = MagicMock()
        calls += 1
        if calls == 1:
            result.until.return_value = button
        else:

            def admitted(predicate: Callable[[WebDriver], bool]) -> None:
                assert predicate(driver)
                order.append("admitted")

            result.until.side_effect = admitted
        return result

    with (
        patch.object(subject.time, "monotonic", side_effect=clock),
        patch.object(subject, "_wait_for_settings_metrics_layout") as layout,
        patch.object(subject, "WebDriverWait", side_effect=wait),
    ):
        layout.side_effect = lambda *_args, **_kwargs: order.append("layout")
        remaining = subject._start_runtime(
            driver,
            runtime_api=api,
            token="synthetic",
            handle="workspace",
            agent_id="agent",
            wait_for_existing_metrics=existing_metrics,
        )
        if existing_metrics:
            layout.assert_called_once_with(driver, deadline=220)
        else:
            layout.assert_not_called()
    assert order == (["layout"] if existing_metrics else []) + ["click", "admitted"]
    button.click.assert_called_once_with()
    assert remaining_waits == expected_waits
    assert remaining == expected_remaining


def test_exhausted_layout_budget_never_clicks() -> None:
    driver = MagicMock(spec=WebDriver)
    api = MagicMock(spec=subject.AgentRuntimeV1Api)
    with (
        patch.object(subject.time, "monotonic", side_effect=[100, 221]),
        patch.object(subject, "_wait_for_settings_metrics_layout"),
        patch.object(subject, "WebDriverWait") as wait,
        pytest.raises(AssertionError, match="original readiness budget"),
    ):
        subject._start_runtime(
            driver,
            runtime_api=api,
            token="synthetic",
            handle="workspace",
            agent_id="agent",
            wait_for_existing_metrics=True,
        )
    wait.assert_not_called()


def test_layout_requires_scope_and_chart_inside_remaining_budget() -> None:
    driver = MagicMock(spec=WebDriver)
    checks: list[bool] = []
    visible_scope = MagicMock()
    chart = MagicMock(side_effect=[False, MagicMock()])

    def wait(_driver: WebDriver, timeout: float, **_kwargs: object) -> MagicMock:
        assert timeout == 7
        result = MagicMock()

        def observe(predicate: Callable[[WebDriver], bool]) -> None:
            checks.extend([predicate(driver), predicate(driver)])

        result.until.side_effect = observe
        return result

    with (
        patch.object(subject.time, "monotonic", return_value=213),
        patch.object(subject, "WebDriverWait", side_effect=wait),
        patch.object(
            subject.ec,
            "visibility_of_element_located",
            side_effect=[visible_scope, chart, visible_scope, chart],
        ),
    ):
        subject._wait_for_settings_metrics_layout(driver, deadline=220)
    assert checks == [False, True]
