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
from azents.core.external_channel_progress import (
    ExternalChannelDesiredProgress,
    ExternalChannelWorkTask,
    checking_progress,
)
from azents.core.slack_external_channel_progress import (
    render_scheduled_task_slack_progress,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelActionResult
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import (
    ScheduledTaskCycleRecord,
)
from azents.runtime.transfer.runtime_to_provider import (
    RuntimeToProviderDeliveryExecutor,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    RuntimeTargetResolver,
)
from azents.services.external_channel.discord_presentation import (
    render_scheduled_task_discord_progress,
)
from azents.services.external_channel.provider_effect import (
    ProviderEffectOutcome,
    ProviderEffectPlan,
    ProviderMutationOutcome,
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
from azents.services.session_resource_authority import SessionResourceAuthority


@dataclasses.dataclass(frozen=True)
class ScheduledTaskProgressExecution:
    """A Scheduled channel action result, or no Scheduled run binding."""

    result: ChannelActionResult | None


@dataclasses.dataclass(frozen=True)
class _ScheduledRunResolution:
    """Whether one Run is Scheduled-bound and its current started cycle."""

    scheduled: bool
    record: ScheduledTaskCycleRecord | None


@dataclasses.dataclass(frozen=True)
class _TrackerEffect:
    """One claimed Scheduled Tracker provider mutation."""

    plan: ProviderEffectPlan
    expected_desired_revision: int
    part_ordinal: int
    state_version: int


class ScheduledTaskChannelService:
    """Own Scheduled provider effects without reusing Channel Work state."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        run_repository: AgentRunRepository,
        cycle_repository: ScheduledTaskCycleRepository,
        provider_repository: ExternalChannelWorkRepository,
        action_service: ExternalChannelActionService,
        config: Config,
    ) -> None:
        self.session_manager = session_manager
        self.run_repository = run_repository
        self.cycle_repository = cycle_repository
        self.provider_repository = provider_repository
        self.action_service = action_service
        self.config = config

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
        async with self.session_manager() as session:
            record = await self.cycle_repository.get_started(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if record is None or record.state.binding_id is None:
                return None
            tracker = await self._claim_tracker_effect(
                session,
                record=record,
                progress=checking_progress(),
            )
        if tracker is None:
            return None
        outcome = await self.action_service.execute_binding_effect(tracker.plan)
        await self._settle_tracker(
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=cycle_id,
            effect=tracker,
            outcome=outcome,
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
        async with self.session_manager() as session:
            resolution = await self._resolve_run_cycle(
                session,
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
            )
            if not resolution.scheduled:
                return ScheduledTaskProgressExecution(result=None)
            record = resolution.record
            if record is None:
                raise ValueError(
                    "The current Scheduled Task cycle is no longer active."
                )
            if mode is not ExternalChannelActionMode.CONTINUE:
                raise ValueError(
                    "Scheduled Task channel_action only supports continue; use "
                    "submit_scheduled_task_result to finish or fail the cycle."
                )
            if record.state.binding_id != binding_id:
                raise ValueError(
                    "Scheduled Task progress requires its exact current Binding."
                )
            if (title is None) != (tasks is None):
                raise ValueError(
                    "Scheduled Task progress requires both a title and task list."
                )
            current = record
            tracker: _TrackerEffect | None = None
            if title is not None and tasks is not None:
                current = await self.cycle_repository.update_progress(
                    session,
                    record=current,
                    progress_title=title,
                    ordered_tasks=[task.title for task in tasks],
                )
                tracker = await self._claim_tracker_effect(
                    session,
                    record=current,
                    progress=ExternalChannelDesiredProgress(
                        schema_version=2,
                        state="working",
                        title=title,
                        tasks=list(tasks),
                    ),
                )
            reply_plans = (
                ()
                if message is None
                else await self.provider_repository.prepare_binding_reply_effects(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    binding_id=binding_id,
                    text=message,
                    files=files,
                    operation_seed=f"scheduled-progress:{current.state.cycle_id}",
                    slack_reply_broadcast=False,
                    discord_forward_to_parent=False,
                )
            )
            state_revision = (
                current.version if tracker is None else tracker.state_version
            )

        outcomes: list[ProviderEffectOutcome] = []
        async with self.session_manager() as effect_session:
            effect_resolution = await self._resolve_run_cycle(
                effect_session,
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
            )
            effect_record = effect_resolution.record
            if effect_record is None:
                outcomes.extend(
                    _inactive_cycle_outcomes(
                        message_requested=message is not None,
                        reply_plans=reply_plans,
                        tracker=tracker,
                    )
                )
            elif effect_record.version != state_revision:
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
                    if (
                        effect_record.state.tracker_desired_revision
                        != tracker.expected_desired_revision
                    ):
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
                        tracker_outcome = (
                            await self.action_service.execute_binding_effect(
                                tracker.plan
                            )
                        )
                        status, provider_message_key = _projection_outcome(
                            operation=tracker.plan.target.operation,
                            outcome=tracker_outcome,
                        )
                        await self.cycle_repository.settle_tracker_projection(
                            effect_session,
                            agent_id=agent_id,
                            session_id=session_id,
                            cycle_id=record.state.cycle_id,
                            expected_desired_revision=(
                                tracker.expected_desired_revision
                            ),
                            part_ordinal=tracker.part_ordinal,
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

    async def _resolve_run_cycle(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
    ) -> _ScheduledRunResolution:
        run = await self.run_repository.get_by_id(session, run_id)
        if run is None:
            return _ScheduledRunResolution(scheduled=False, record=None)
        if run.session_id != session_id:
            raise ValueError("The current AgentRun does not belong to this Session.")
        if run.scheduled_task_cycle_id is None:
            return _ScheduledRunResolution(scheduled=False, record=None)
        cycle = await self.cycle_repository.lock(
            session,
            agent_id=agent_id,
            session_id=session_id,
            cycle_id=run.scheduled_task_cycle_id,
        )
        if (
            cycle is None
            or cycle.state.phase != "started"
            or cycle.state.current_run_id != run_id
        ):
            return _ScheduledRunResolution(scheduled=True, record=None)
        return _ScheduledRunResolution(scheduled=True, record=cycle)

    async def _claim_tracker_effect(
        self,
        session: AsyncSession,
        *,
        record: ScheduledTaskCycleRecord,
        progress: ExternalChannelDesiredProgress,
    ) -> _TrackerEffect | None:
        binding_id = record.state.binding_id
        if binding_id is None:
            return None
        desired_revision = record.state.tracker_desired_revision
        current_part = next(
            (
                part
                for part in record.state.tracker_current_projection_parts
                if part.part_ordinal == 0
            ),
            None,
        )
        operation = (
            ExternalChannelDeliveryOperation.PROGRESS_UPDATE
            if current_part is not None
            and current_part.provider_message_key is not None
            else ExternalChannelDeliveryOperation.PROGRESS_CREATE
        )
        slack = render_scheduled_task_slack_progress(
            progress,
            scheduled_task_title=record.state.title,
            work_id=record.state.cycle_id,
            desired_progress_revision=desired_revision,
        )
        discord = render_scheduled_task_discord_progress(
            progress,
            scheduled_task_title=record.state.title,
            work_id=record.state.cycle_id,
            desired_progress_revision=desired_revision,
        )
        if not discord.pages:
            raise RuntimeError("Scheduled Tracker rendering produced no Discord page.")
        page = discord.pages[0]
        slack_payload: dict[str, object] = {
            "text": slack.text,
            "blocks": slack.blocks,
            "desired_progress_revision": desired_revision,
            "tracker_kind": "scheduled_task",
        }
        discord_payload: dict[str, object] = {
            "text": page.text,
            "embeds": page.embeds,
            "desired_progress_revision": desired_revision,
            "tracker_kind": "scheduled_task",
        }
        if current_part is not None and current_part.provider_message_key is not None:
            slack_payload["provider_message_key"] = current_part.provider_message_key
            discord_payload["provider_message_key"] = current_part.provider_message_key
        plan = await self.provider_repository.prepare_binding_effect(
            session,
            agent_id=record.state.agent_id,
            session_id=record.state.session_id,
            binding_id=binding_id,
            operation=operation,
            slack_payload=slack_payload,
            discord_payload=discord_payload,
            operation_seed=(
                f"scheduled-tracker:{record.state.cycle_id}:{desired_revision}:0"
            ),
        )
        if plan is None:
            return None
        claimed = await self.cycle_repository.claim_tracker_projection(
            session,
            agent_id=record.state.agent_id,
            session_id=record.state.session_id,
            cycle_id=record.state.cycle_id,
            expected_desired_revision=desired_revision,
            part_ordinal=0,
        )
        if claimed is None:
            return None
        return _TrackerEffect(
            plan=plan,
            expected_desired_revision=desired_revision,
            part_ordinal=0,
            state_version=claimed.version,
        )

    async def _settle_tracker(
        self,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
        effect: _TrackerEffect,
        outcome: ProviderMutationOutcome | None,
    ) -> None:
        status, provider_message_key = _projection_outcome(
            operation=effect.plan.target.operation,
            outcome=outcome,
        )
        async with self.session_manager() as session:
            await self.cycle_repository.settle_tracker_projection(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
                expected_desired_revision=effect.expected_desired_revision,
                part_ordinal=effect.part_ordinal,
                status=status,
                provider_message_key=provider_message_key,
            )


def get_scheduled_task_channel_service(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)],
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
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
        run_repository=run_repository,
        cycle_repository=cycle_repository,
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
    tracker: _TrackerEffect | None,
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
    tracker: _TrackerEffect | None,
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
