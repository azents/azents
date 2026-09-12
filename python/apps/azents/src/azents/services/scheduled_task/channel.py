"""Scheduled-owned External Channel presentation and progress orchestration."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated, NamedTuple

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelWorkProjectionStatus,
    ExternalChannelWorkStatus,
)
from azents.core.external_channel_file import ExternalChannelOutboundFileManifest
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.external_channel_provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
    ProviderMutationOutcome,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelActionResult
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task_cycle.progress import (
    ScheduledTaskProgressRepository,
)
from azents.repos.scheduled_task_cycle.progress_data import (
    ScheduledTaskProgressPreparation,
    ScheduledTaskTrackerEffect,
)
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    RuntimeTargetResolver,
)
from azents.services.file_storage import FileStorage
from azents.services.scheduled_task.control import (
    build_scheduled_task_control_locator,
    render_scheduled_task_discord_deletion,
    render_scheduled_task_discord_registration,
    render_scheduled_task_slack_deletion,
    render_scheduled_task_slack_registration,
)
from azents.services.scheduled_task.terminal import (
    ScheduledTaskTerminalEffectSnapshot,
)
from azents.services.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
)


@dataclasses.dataclass(frozen=True)
class ScheduledTaskProgressExecution:
    """A Scheduled channel action result, or no Scheduled run binding."""

    result: ChannelActionResult | None


class ScheduledTaskChannelService:
    """Own Scheduled provider effects without reusing Channel Work state."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        progress_repository: ScheduledTaskProgressRepository,
        provider_repository: ExternalChannelWorkRepository,
        action_service: ExternalChannelActionService,
        config: Config,
    ) -> None:
        self.session_manager = session_manager
        self.progress_repository = progress_repository
        self.provider_repository = provider_repository
        self.action_service = action_service
        self.config = config

    def for_execution(
        self,
        owner: SessionExecutionOwner,
    ) -> "ScheduledTaskChannelService":
        """Bind Scheduled channel persistence to one durable Session owner."""
        return ScheduledTaskChannelService(
            session_manager=OwnerBoundSessionManager(
                session_manager=self.session_manager,
                session_id=owner.session_id,
                owner_generation=owner.owner_generation,
            ),
            progress_repository=self.progress_repository.for_execution(owner),
            provider_repository=self.provider_repository,
            action_service=self.action_service.for_execution_owner(owner),
            config=self.config,
        )

    async def execute_registration(
        self,
        task: ScheduledTask,
    ) -> ProviderEffectOutcome | None:
        """Attempt one post-create registration presentation after Task commit."""
        binding_id = task.binding_id
        if binding_id is None:
            return None
        edit_locator = build_scheduled_task_control_locator(
            secret=self.config.auth.jwt.secret_key,
            action="edit",
            task_id=task.id,
            binding_id=binding_id,
        )
        delete_locator = build_scheduled_task_control_locator(
            secret=self.config.auth.jwt.secret_key,
            action="delete",
            task_id=task.id,
            binding_id=binding_id,
        )
        slack_render = render_scheduled_task_slack_registration(
            task=task,
            edit_locator=edit_locator,
            delete_locator=delete_locator,
        )
        discord_render = render_scheduled_task_discord_registration(task=task)
        async with self.session_manager() as session:
            plan = await self.provider_repository.prepare_binding_effect(
                session,
                agent_id=task.agent_id,
                session_id=task.session_id,
                binding_id=binding_id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                slack_payload={
                    "control_kind": "scheduled_task_registration",
                    "text": slack_render.text,
                    "blocks": slack_render.payload,
                },
                discord_payload={
                    "control_kind": "scheduled_task_registration",
                    "text": discord_render.text,
                    "embeds": discord_render.payload,
                    "task_id": task.id,
                    "delete_locator": delete_locator,
                },
                operation_seed=f"scheduled-registration:{task.id}",
            )
        if plan is None:
            return _unavailable_outcome(
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                part=0,
            )
        outcome = await self.action_service.execute_binding_effect(plan)
        return _provider_outcome(
            operation=plan.target.operation,
            part=0,
            outcome=outcome,
        )

    async def execute_deletion(
        self,
        task: ScheduledTask,
    ) -> ProviderEffectOutcome | None:
        """Attempt one post-delete notification after Task deletion commits."""
        binding_id = task.binding_id
        if binding_id is None:
            return None
        plan = await self.prepare_deletion(task)
        if plan is None:
            return _unavailable_outcome(
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                part=0,
            )
        return await self.execute_deletion_plan(plan)

    async def prepare_deletion(
        self,
        task: ScheduledTask,
    ) -> ProviderEffectPlan | None:
        """Prepare one exact-Binding deletion notice without provider I/O."""
        binding_id = task.binding_id
        if binding_id is None:
            return None
        slack_render = render_scheduled_task_slack_deletion(task=task)
        discord_render = render_scheduled_task_discord_deletion(task=task)
        async with self.session_manager() as session:
            return await self.provider_repository.prepare_binding_effect(
                session,
                agent_id=task.agent_id,
                session_id=task.session_id,
                binding_id=binding_id,
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                slack_payload={
                    "control_kind": "scheduled_task_deletion",
                    "text": slack_render.text,
                    "blocks": slack_render.payload,
                },
                discord_payload={
                    "control_kind": "scheduled_task_deletion",
                    "text": discord_render.text,
                    "embeds": discord_render.payload,
                },
                operation_seed=f"scheduled-deletion:{task.id}",
            )

    async def execute_deletion_plan(
        self,
        plan: ProviderEffectPlan,
    ) -> ProviderEffectOutcome:
        """Attempt one prepared deletion notice against unchanged Binding authority."""
        outcome = await self.action_service.execute_binding_effect(plan)
        return _provider_outcome(
            operation=plan.target.operation,
            part=0,
            outcome=outcome,
        )

    async def create_initial_tracker(
        self,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ProviderEffectOutcome | None:
        """Attempt the run-start Tracker create once after admission commits."""
        tracker = await self.progress_repository.prepare_initial_tracker(
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=cycle_id,
        )
        if tracker is None:
            return None
        outcome = await self.action_service.execute_binding_effect(tracker.plan)
        status, provider_message_key = _projection_outcome(
            operation=tracker.plan.target.operation,
            outcome=outcome,
        )
        await self.progress_repository.settle_tracker(
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=cycle_id,
            effect=tracker,
            status=status,
            provider_message_key=provider_message_key,
        )
        return _provider_outcome(
            operation=tracker.plan.target.operation,
            part=tracker.part_ordinal,
            outcome=outcome,
        )

    async def execute_progress(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        binding_id: str,
        mode: ExternalChannelActionMode,
        message: str | None,
        title: str | None,
        tasks: Sequence[ExternalChannelWorkTask] | None,
        files: Sequence[ExternalChannelOutboundFileManifest],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> ScheduledTaskProgressExecution:
        """Route one current Scheduled Run action before Channel Work mutation."""
        preparation = await self.progress_repository.prepare_progress(
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            binding_id=binding_id,
            mode=mode,
            message=message,
            title=title,
            tasks=tasks,
            files=files,
        )
        if preparation.status == "not_scheduled":
            return ScheduledTaskProgressExecution(result=None)
        if preparation.status == "inactive":
            raise ValueError("The current Scheduled Task cycle is no longer active.")
        cycle_id, state_revision = _prepared_progress_identity(preparation)
        reply_plans = preparation.reply_plans
        tracker = preparation.tracker

        outcomes: list[ProviderEffectOutcome] = []
        admission = await self.progress_repository.admit_progress_effects(
            agent_id=agent_id,
            session_id=session_id,
            run_id=run_id,
            state_revision=state_revision,
            tracker_expected_desired_revision=(
                None if tracker is None else tracker.expected_desired_revision
            ),
        )
        if admission.status == "inactive":
            outcomes.extend(
                _inactive_cycle_outcomes(
                    message_requested=message is not None,
                    reply_plans=reply_plans,
                    tracker=tracker,
                )
            )
        elif admission.status == "superseded":
            outcomes.extend(
                _superseded_progress_outcomes(
                    message_requested=message is not None,
                    reply_plans=reply_plans,
                    tracker=tracker,
                )
            )
        else:
            if message is not None and not reply_plans:
                outcomes.append(
                    _unavailable_outcome(
                        operation=ExternalChannelDeliveryOperation.REPLY,
                        part=0,
                    )
                )
            for part, plan in enumerate(reply_plans):
                outcome = await self.action_service.execute_binding_effect(
                    plan,
                    file_storage=file_storage,
                    agent_id=agent_id,
                    session_id=session_id,
                    authority=authority,
                    provider_delivery_service=provider_delivery_service,
                    resolve_runtime_target=resolve_runtime_target,
                )
                outcomes.append(
                    _provider_outcome(
                        operation=plan.target.operation,
                        part=part,
                        outcome=outcome,
                    )
                )
            if tracker is not None:
                if not admission.tracker_current:
                    outcomes.append(
                        _not_attempted_outcome(
                            operation=tracker.plan.target.operation,
                            part=tracker.part_ordinal,
                            reason="scheduled_progress_superseded",
                            detail=(
                                "A newer Scheduled Task progress revision "
                                "superseded this provider effect."
                            ),
                        )
                    )
                else:
                    tracker_outcome = await self.action_service.execute_binding_effect(
                        tracker.plan
                    )
                    status, provider_message_key = _projection_outcome(
                        operation=tracker.plan.target.operation,
                        outcome=tracker_outcome,
                    )
                    await self.progress_repository.settle_tracker(
                        agent_id=agent_id,
                        session_id=session_id,
                        cycle_id=cycle_id,
                        effect=tracker,
                        status=status,
                        provider_message_key=provider_message_key,
                    )
                    outcomes.append(
                        _provider_outcome(
                            operation=tracker.plan.target.operation,
                            part=tracker.part_ordinal,
                            outcome=tracker_outcome,
                        )
                    )
        return ScheduledTaskProgressExecution(
            result=ChannelActionResult(
                binding_id=binding_id,
                work_status=ExternalChannelWorkStatus.ACTIVE,
                state_revision=state_revision,
                awaiting_input=False,
                outcomes=tuple(outcomes),
            )
        )

    async def execute_terminal(
        self,
        snapshot: ScheduledTaskTerminalEffectSnapshot,
        *,
        files: Sequence[ExternalChannelOutboundFileManifest],
        file_storage: FileStorage | None,
        authority: SessionResourceAuthority | None,
        provider_delivery_service: RuntimeToProviderDeliveryExecutor | None,
        resolve_runtime_target: RuntimeTargetResolver | None,
    ) -> tuple[ProviderEffectOutcome, ...]:
        """Publish terminal parts then attempt every captured Tracker cleanup."""
        async with self.session_manager() as session:
            reply_plans = await self.provider_repository.prepare_binding_reply_effects(
                session,
                agent_id=snapshot.agent_id,
                session_id=snapshot.session_id,
                binding_id=snapshot.binding_id,
                text=snapshot.result,
                files=files,
                operation_seed=f"scheduled-terminal:{snapshot.cycle_id}",
                slack_reply_broadcast=True,
                discord_forward_to_parent=True,
            )
            cleanup_plans: list[tuple[int, ProviderEffectPlan]] = []
            for part in snapshot.tracker_projection_parts:
                if part.provider_message_key is None:
                    continue
                plan = await self.provider_repository.prepare_binding_effect(
                    session,
                    agent_id=snapshot.agent_id,
                    session_id=snapshot.session_id,
                    binding_id=snapshot.binding_id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                    slack_payload={
                        "provider_message_key": part.provider_message_key,
                    },
                    discord_payload={
                        "provider_message_key": part.provider_message_key,
                    },
                    operation_seed=(
                        f"scheduled-tracker-delete:{snapshot.cycle_id}:"
                        f"{part.part_ordinal}"
                    ),
                )
                if plan is not None:
                    cleanup_plans.append((part.part_ordinal, plan))

        outcomes: list[ProviderEffectOutcome] = []
        if not reply_plans:
            outcomes.append(
                _unavailable_outcome(
                    operation=ExternalChannelDeliveryOperation.REPLY,
                    part=0,
                )
            )
        for part, plan in enumerate(reply_plans):
            outcome = await self.action_service.execute_binding_effect(
                plan,
                file_storage=file_storage,
                agent_id=snapshot.agent_id,
                session_id=snapshot.session_id,
                authority=authority,
                provider_delivery_service=provider_delivery_service,
                resolve_runtime_target=resolve_runtime_target,
            )
            outcomes.append(
                _provider_outcome(
                    operation=plan.target.operation,
                    part=part,
                    outcome=outcome,
                )
            )
        planned_cleanup_ordinals = {ordinal for ordinal, _ in cleanup_plans}
        for part in snapshot.tracker_projection_parts:
            if (
                part.provider_message_key is not None
                and part.part_ordinal not in planned_cleanup_ordinals
            ):
                outcomes.append(
                    _unavailable_outcome(
                        operation=ExternalChannelDeliveryOperation.PROGRESS_DELETE,
                        part=part.part_ordinal,
                    )
                )
        for part, plan in cleanup_plans:
            outcome = await self.action_service.execute_binding_effect(plan)
            outcomes.append(
                _provider_outcome(
                    operation=plan.target.operation,
                    part=part,
                    outcome=outcome,
                )
            )
        return tuple(outcomes)


def get_scheduled_task_channel_service(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    progress_repository: Annotated[
        ScheduledTaskProgressRepository, Depends(ScheduledTaskProgressRepository)
    ],
    provider_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ],
    action_service: Annotated[ExternalChannelActionService, Depends()],
    config: Annotated[Config, Depends(get_config)],
) -> ScheduledTaskChannelService:
    """Create the Scheduled-owned External Channel effect service."""
    return ScheduledTaskChannelService(
        session_manager=session_manager,
        progress_repository=progress_repository,
        provider_repository=provider_repository,
        action_service=action_service,
        config=config,
    )


class _ProjectionOutcome(NamedTuple):
    """Provider projection status and its optional message identity."""

    status: ExternalChannelWorkProjectionStatus
    provider_message_key: str | None


def _projection_outcome(
    *,
    operation: ExternalChannelDeliveryOperation,
    outcome: ProviderMutationOutcome | None,
) -> _ProjectionOutcome:
    if outcome is None:
        return _ProjectionOutcome(ExternalChannelWorkProjectionStatus.UNKNOWN, None)
    if outcome.status == "failed":
        return _ProjectionOutcome(
            ExternalChannelWorkProjectionStatus.FAILED,
            outcome.provider_message_key,
        )
    if outcome.status == "unknown":
        return _ProjectionOutcome(
            ExternalChannelWorkProjectionStatus.UNKNOWN,
            outcome.provider_message_key,
        )
    if operation is ExternalChannelDeliveryOperation.PROGRESS_DELETE:
        return _ProjectionOutcome(ExternalChannelWorkProjectionStatus.DELETED, None)
    if outcome.provider_message_key is None:
        return _ProjectionOutcome(ExternalChannelWorkProjectionStatus.UNKNOWN, None)
    return _ProjectionOutcome(
        ExternalChannelWorkProjectionStatus.PRESENT,
        outcome.provider_message_key,
    )


def _prepared_progress_identity(
    preparation: ScheduledTaskProgressPreparation,
) -> tuple[str, int]:
    """Return required identities from one successful preparation."""
    if (
        preparation.status != "prepared"
        or preparation.cycle_id is None
        or preparation.state_revision is None
    ):
        raise RuntimeError("Scheduled progress preparation is incomplete.")
    return preparation.cycle_id, preparation.state_revision


def _provider_outcome(
    *,
    operation: ExternalChannelDeliveryOperation,
    part: int,
    outcome: ProviderMutationOutcome | None,
) -> ProviderEffectOutcome:
    if outcome is None:
        return _unavailable_outcome(operation=operation, part=part)
    return ProviderEffectOutcome(
        operation=operation,
        part=part,
        status=outcome.status,
        reason=outcome.error_kind,
        detail=outcome.error_summary,
    )


def _inactive_cycle_outcomes(
    *,
    message_requested: bool,
    reply_plans: Sequence[ProviderEffectPlan],
    tracker: ScheduledTaskTrackerEffect | None,
) -> list[ProviderEffectOutcome]:
    """Report every provider effect suppressed by terminalization winning."""
    outcomes = [
        _not_attempted_outcome(
            operation=plan.target.operation,
            part=part,
            reason="scheduled_cycle_inactive",
            detail="The Scheduled Task cycle ended before provider publication.",
        )
        for part, plan in enumerate(reply_plans)
    ]
    if message_requested and not reply_plans:
        outcomes.append(
            _not_attempted_outcome(
                operation=ExternalChannelDeliveryOperation.REPLY,
                part=0,
                reason="scheduled_cycle_inactive",
                detail="The Scheduled Task cycle ended before provider publication.",
            )
        )
    if tracker is not None:
        outcomes.append(
            _not_attempted_outcome(
                operation=tracker.plan.target.operation,
                part=tracker.part_ordinal,
                reason="scheduled_cycle_inactive",
                detail="The Scheduled Task cycle ended before provider publication.",
            )
        )
    return outcomes


def _superseded_progress_outcomes(
    *,
    message_requested: bool,
    reply_plans: Sequence[ProviderEffectPlan],
    tracker: ScheduledTaskTrackerEffect | None,
) -> list[ProviderEffectOutcome]:
    """Report every provider effect suppressed by a newer progress revision."""
    outcomes = [
        _not_attempted_outcome(
            operation=plan.target.operation,
            part=part,
            reason="scheduled_progress_superseded",
            detail="A newer Scheduled Task progress revision superseded this effect.",
        )
        for part, plan in enumerate(reply_plans)
    ]
    if message_requested and not reply_plans:
        outcomes.append(
            _not_attempted_outcome(
                operation=ExternalChannelDeliveryOperation.REPLY,
                part=0,
                reason="scheduled_progress_superseded",
                detail=(
                    "A newer Scheduled Task progress revision superseded this effect."
                ),
            )
        )
    if tracker is not None:
        outcomes.append(
            _not_attempted_outcome(
                operation=tracker.plan.target.operation,
                part=tracker.part_ordinal,
                reason="scheduled_progress_superseded",
                detail=(
                    "A newer Scheduled Task progress revision superseded this effect."
                ),
            )
        )
    return outcomes


def _not_attempted_outcome(
    *,
    operation: ExternalChannelDeliveryOperation,
    part: int,
    reason: str,
    detail: str,
) -> ProviderEffectOutcome:
    return ProviderEffectOutcome(
        operation=operation,
        part=part,
        status="not_attempted",
        reason=reason,
        detail=detail,
    )


def _unavailable_outcome(
    *,
    operation: ExternalChannelDeliveryOperation,
    part: int,
) -> ProviderEffectOutcome:
    return _not_attempted_outcome(
        operation=operation,
        part=part,
        reason="provider_authority_unavailable",
        detail="Current External Channel provider authority is unavailable.",
    )
