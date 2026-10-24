"""Application status reconciliation and lost-response recovery without replay."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.browser_configuration import (
    BROWSER_CONFIGURATION_CAPABILITY,
    BrowserConfigurationRequest,
    BrowserConfigurationStatus,
    BrowserImplementation,
)

from azents.core.browser_configuration import BrowserApplicationClaim
from azents.repos.browser_configuration import BrowserConfigurationRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeConnectionRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore
from azents.services.browser_configuration import BrowserConfigurationCoordinator


@dataclass(frozen=True)
class Harness:
    coordinator: BrowserConfigurationCoordinator
    repository: AsyncMock
    runner: AsyncMock
    coordination: AsyncMock
    claim: BrowserApplicationClaim


def harness() -> Harness:
    now = datetime.now(UTC)
    claim = BrowserApplicationClaim(
        "agent",
        "current",
        BrowserImplementation.CAMOUFOX,
        "claim",
        "runtime",
        7,
        3,
        4,
        now + timedelta(minutes=2),
    )
    repository = AsyncMock(spec=BrowserConfigurationRepository)
    repository.claim_due.return_value = claim
    repository.claim_current.return_value = True
    repository.finish.return_value = True
    runner = AsyncMock(spec=RuntimeRunnerOperationClient)
    coordination = AsyncMock(spec=RuntimeCoordinationStore)
    coordination.get_connection.return_value = RuntimeConnectionRecord(
        RuntimeConnectionKind.RUNNER,
        "runtime",
        "connection",
        "control",
        7,
        now,
        now,
        now + timedelta(minutes=1),
        {"capabilities": ["browser.v1", BROWSER_CONFIGURATION_CAPABILITY]},
    )
    return Harness(
        BrowserConfigurationCoordinator(repository, runner, coordination),
        repository,
        runner,
        coordination,
        claim,
    )


async def test_runner_report_reconciles_only_current_bound_agent() -> None:
    item = harness()
    item.repository.agent_for_runtime.return_value = "agent"
    item.runner.browser_configuration_control.return_value = BrowserConfigurationStatus(
        "current", BrowserImplementation.CAMOUFOX, "ready", None
    )
    await item.coordinator.reconcile_runtime("runtime", 7)
    item.repository.agent_for_runtime.assert_awaited_once_with("runtime", 7)
    item.runner.browser_configuration_control.assert_awaited_once()


async def test_former_runner_report_cannot_trigger_application() -> None:
    item = harness()
    item.repository.agent_for_runtime.return_value = None
    await item.coordinator.reconcile_runtime("runtime", 6)
    item.repository.claim_due.assert_not_awaited()
    item.runner.browser_configuration_control.assert_not_awaited()


async def test_status_reconciliation_does_not_reset_correct_browser() -> None:
    item = harness()
    ready = BrowserConfigurationStatus(
        "current", BrowserImplementation.CAMOUFOX, "ready", None
    )
    item.runner.browser_configuration_control.return_value = ready
    assert await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_awaited_once()
    assert item.runner.browser_configuration_control.call_args.kwargs["request"] is None
    assert item.repository.finish.call_args.args[:2] == (item.claim, ready)


async def test_new_intent_applies_with_exact_runner_observed_predecessor() -> None:
    item = harness()
    item.runner.browser_configuration_control.side_effect = [
        BrowserConfigurationStatus(
            "old", BrowserImplementation.PATCHRIGHT, "ready", None
        ),
        BrowserConfigurationStatus(
            "current", BrowserImplementation.CAMOUFOX, "ready", None
        ),
    ]
    await item.coordinator.apply_once("agent")
    assert item.runner.browser_configuration_control.await_count == 2
    assert item.runner.browser_configuration_control.call_args.kwargs[
        "request"
    ] == BrowserConfigurationRequest("current", "old", BrowserImplementation.CAMOUFOX)
    item.repository.finish.assert_awaited_once()


@pytest.mark.parametrize("state", ["applying", "failed"])
async def test_in_progress_and_failed_current_intent_are_not_reapplied(
    state: str,
) -> None:
    item = harness()
    status = (
        BrowserConfigurationStatus(
            "current", BrowserImplementation.CAMOUFOX, "applying", None
        )
        if state == "applying"
        else BrowserConfigurationStatus(
            "current", BrowserImplementation.CAMOUFOX, "failed", "browser_unavailable"
        )
    )
    item.runner.browser_configuration_control.return_value = status
    await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_awaited_once()
    if state == "applying":
        item.repository.defer.assert_awaited_once()
        item.repository.finish.assert_not_awaited()
    else:
        item.repository.finish.assert_awaited_once()


async def test_superseded_claim_cannot_send_configuration_or_accept_result() -> None:
    item = harness()
    item.repository.claim_current.return_value = False
    item.runner.browser_configuration_control.return_value = BrowserConfigurationStatus(
        None, None, "unconfigured", None
    )
    await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_awaited_once()
    item.repository.finish.assert_not_awaited()


async def test_lost_response_defers_for_same_identity_reconciliation() -> None:
    item = harness()
    item.runner.browser_configuration_control.side_effect = (
        RuntimeRunnerOperationUnavailable("Control lost")
    )
    await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_awaited_once()
    item.repository.defer.assert_awaited_once()
    item.repository.finish.assert_not_awaited()


async def test_unsupported_runner_never_receives_unknown_control_or_fallback() -> None:
    item = harness()
    connection = item.coordination.get_connection.return_value
    assert isinstance(connection, RuntimeConnectionRecord)
    item.coordination.get_connection.return_value = replace(
        connection, metadata={"capabilities": ["browser.v1"]}
    )
    await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_not_awaited()
    status = item.repository.finish.call_args.args[1]
    assert isinstance(status, BrowserConfigurationStatus)
    assert status.state == "failed"
    assert status.reason_code == "browser_configuration_unsupported"


async def test_offline_runtime_never_allocates_or_dispatches() -> None:
    item = harness()
    item.coordination.get_connection.return_value = None
    await item.coordinator.apply_once("agent")
    item.runner.browser_configuration_control.assert_not_awaited()
    item.repository.defer.assert_awaited_once()
