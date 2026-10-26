"""Deterministic tests for setup preparation dispatch and recovery boundaries."""

import asyncio
import datetime
import logging
from typing import NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelSetupPreparationBoundary,
    ExternalChannelTriggerLocator,
)
from azents.core.external_channel_provider_effect import (
    ProviderMutationOutcome,
    ProviderMutationStatus,
)
from azents.job_runtime.local import JobRuntimeClosedError
from azents.repos.external_channel.action_operations import (
    ExternalChannelActionOperations,
)
from azents.repos.external_channel.setup_preparation import SetupPreparationAttempt
from azents.services.external_channel.channel_action import ExternalChannelActionService
from azents.services.external_channel.setup_preparation import (
    ExternalChannelSetupPreparationService,
)
from azents.services.external_channel.setup_preparation_job import (
    build_setup_preparation_job,
)
from azents.testing.external_channel import make_provider_effect_plan
from azents.testing.types import require_instance


def _request() -> ExternalChannelIngestionRequest:
    return ExternalChannelIngestionRequest(
        locator=ExternalChannelTriggerLocator(
            connection_id="connection",
            provider=ExternalChannelProvider.DISCORD,
            provider_event_type="discord_message_create",
            provider_tenant_id="100",
            provider_channel_id="200",
            provider_parent_channel_id="200",
            provider_thread_key=None,
            delivery_thread_key="600",
            provider_resource_key="discord:100:600",
            trigger_provider_message_key="discord:100:600",
            trigger_provider_message_id="600",
            trigger_position="00000000000000000600",
            provider_user_id="400",
            invocation=True,
            expected_file_count=None,
        ),
        scope=ExternalChannelConversationScope(
            connection_id="connection",
            kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id="200",
            provider_thread_key=None,
        ),
        authority=ExternalChannelIngressAuthority(
            kind=ExternalChannelIngressAuthorityKind.DURABLE_REPLAY,
            ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
            configuration_generation=1,
            lease_owner=None,
            lease_generation=None,
        ),
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=2)
        ),
        operation=ExternalChannelIngestionOperation.SETUP_PREPARATION,
        selected_route_id=None,
        replay_boundary=ExternalChannelSetupPreparationBoundary(
            connection_id="connection",
            source_resource_id="resource",
            target_resource_id="resource",
            principal_id="principal",
            trigger_provider_message_key="discord:100:600",
            conversation_position_id="position",
            range_start_position=None,
            trigger_position="00000000000000000600",
            claim_id="claim",
            claim_generation=1,
            source_revision=1,
            preparation_owner="owner",
            configuration_generation=1,
        ),
        initial_title_eligible=False,
    )


class _Fixture(NamedTuple):
    service: ExternalChannelSetupPreparationService
    operations: MagicMock
    runtime: MagicMock
    ingestion: MagicMock
    controls: MagicMock


def _service(request: ExternalChannelIngestionRequest) -> _Fixture:
    operations = MagicMock(
        claim=AsyncMock(return_value=SetupPreparationAttempt(request, None)),
        transition=AsyncMock(return_value=True),
        admit=AsyncMock(return_value="claim"),
        recoverable_ids=AsyncMock(return_value=["claim"]),
    )
    runtime = MagicMock(submit=AsyncMock())
    ingestion = MagicMock(ingest=AsyncMock())
    controls = MagicMock(attempt=AsyncMock())
    return _Fixture(
        ExternalChannelSetupPreparationService(
            operations=operations,
            job_runtime=runtime,
            ingestion_service=ingestion,
            provider_control=controls,
        ),
        operations,
        runtime,
        ingestion,
        controls,
    )


@pytest.mark.asyncio
async def test_lost_runtime_submission_keeps_committed_claim_recoverable() -> None:
    request = _request()
    fixture = _service(request)
    service = fixture.service
    fixture.runtime.submit.side_effect = JobRuntimeClosedError("closed")
    outcome = await service.admit(request)
    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION
    fixture.operations.admit.assert_awaited_once()
    fixture.runtime.submit.side_effect = None
    await service.recover(now=datetime.datetime.now(datetime.UTC), limit=10)
    assert fixture.runtime.submit.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["delivered", "failed", "unknown"])
async def test_dispatch_is_committed_before_provider_effect_and_unknown_is_not_retried(
    delivery: ProviderMutationStatus,
) -> None:
    request = _request()
    fixture = _service(request)
    service = fixture.service
    plan = make_provider_effect_plan()
    fixture.ingestion.ingest.return_value = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.AWAITING_SELECTION,
        reason=ExternalChannelIngestionReason.SETUP_REQUIRED,
        mailbox_item_id=None,
        control_plans=(plan,),
        connection_id="connection",
    )

    async def deliver(
        _plan: object, *, preparation_boundary: ExternalChannelSetupPreparationBoundary
    ) -> ProviderMutationOutcome:
        assert preparation_boundary == request.replay_boundary
        calls = fixture.operations.transition.await_args_list
        assert calls[-1].kwargs["dispatch"] is True
        return ProviderMutationOutcome(
            status=delivery,
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )

    fixture.controls.attempt.side_effect = deliver
    await service.process("claim", deadline=request.deadline)
    fixture.controls.attempt.assert_awaited_once_with(
        plan, preparation_boundary=request.replay_boundary
    )
    assert fixture.operations.transition.await_args_list[-1].kwargs["retry"] == (
        delivery == "failed"
    )


@pytest.mark.asyncio
async def test_provider_reads_can_block_without_losing_the_claim() -> None:
    request = _request()
    fixture = _service(request)
    service = fixture.service
    entered = asyncio.Event()
    release = asyncio.Event()

    async def read(
        _request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionOutcome:
        entered.set()
        await release.wait()
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.IGNORED,
            reason=ExternalChannelIngestionReason.AUTHOR_NOT_ELIGIBLE,
            mailbox_item_id=None,
            control_plans=(),
            connection_id=None,
        )

    fixture.ingestion.ingest.side_effect = read
    task = asyncio.create_task(service.process("claim", deadline=request.deadline))
    try:
        await entered.wait()
        fixture.operations.transition.assert_not_awaited()
    finally:
        release.set()
        await task
    fixture.operations.transition.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_preparation_keeps_lease_for_recovery() -> None:
    request = _request()
    fixture = _service(request)
    service = fixture.service
    fixture.ingestion.ingest.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service.process("claim", deadline=request.deadline)
    fixture.operations.transition.assert_not_awaited()


def test_setup_job_is_content_free_and_not_bound_to_gateway_lease() -> None:
    now = datetime.datetime.now(datetime.UTC)
    job = build_setup_preparation_job("claim", now=now)
    assert job.payload == {"claim_id": "claim"}
    assert job.deadline - now == datetime.timedelta(minutes=2)


@pytest.mark.asyncio
async def test_terminal_rejection_logs_sanitized_evidence_and_does_not_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = _request()
    fixture = _service(request)
    fixture.ingestion.ingest.return_value = ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
        reason=ExternalChannelIngestionReason.INVALID_REPLAY_BOUNDARY,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )
    with caplog.at_level(logging.WARNING):
        await fixture.service.process("claim", deadline=request.deadline)
    fixture.controls.attempt.assert_not_awaited()
    fixture.operations.transition.assert_awaited_once()
    assert fixture.operations.transition.await_args.kwargs["retry"] is False
    assert fixture.operations.transition.await_args.kwargs["dispatch"] is False
    records = [
        record
        for record in caplog.records
        if record.message == "Setup preparation rejected permanently"
    ]
    assert len(records) == 1
    assert records[0].__dict__["failure_code"] == "invalid_replay_boundary"
    assert records[0].__dict__["external_channel_setup_claim_id"] == "claim"


@pytest.mark.asyncio
async def test_changed_dispatch_boundary_never_calls_provider() -> None:
    request = _request()
    boundary = request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    plan = make_provider_effect_plan()
    operations = AsyncMock(spec=ExternalChannelActionOperations)
    operations.revalidate_direct_control.return_value = None
    deliver = AsyncMock()
    service = require_instance(
        MagicMock(
            spec=ExternalChannelActionService,
            operations=operations,
            _deliver=deliver,
        ),
        ExternalChannelActionService,
    )
    assert (
        await ExternalChannelActionService.execute_direct_control(
            service,
            plan,
            preparation_boundary=boundary,
        )
        is None
    )
    operations.revalidate_direct_control.assert_awaited_once_with(
        plan=plan, preparation_boundary=boundary
    )
    deliver.assert_not_awaited()
