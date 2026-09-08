"""Repository-owned Scheduled Task progress database operations."""

import dataclasses
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.discord_external_channel_presentation import (
    render_scheduled_task_discord_progress,
)
from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelWorkProjectionStatus,
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
from azents.repos.scheduled_task.presentation import render_scheduled_task_schedule
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleRecord
from azents.repos.scheduled_task_cycle.progress_data import (
    ScheduledTaskProgressAdmission,
    ScheduledTaskProgressPreparation,
    ScheduledTaskTrackerEffect,
)


@dataclasses.dataclass(frozen=True)
class _ScheduledRunResolution:
    """Whether one Run is Scheduled-bound and its current started cycle."""

    scheduled: bool
    record: ScheduledTaskCycleRecord | None


@dataclasses.dataclass
class ScheduledTaskProgressRepository:
    """Own database-only Scheduled Task progress operations."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ]
    provider_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ]

    async def prepare_initial_tracker(
        self,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
    ) -> ScheduledTaskTrackerEffect | None:
        """Prepare and claim one initial Tracker in a completed transaction."""
        async with self.session_manager() as session:
            record = await self.cycle_repository.get_started(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
            )
            if record is None or record.state.binding_id is None:
                return None
            claimed = await self._claim_tracker_effect(
                session,
                record=record,
                progress=checking_progress(),
            )
            return None if claimed is None else claimed.effect

    async def prepare_progress(
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
    ) -> ScheduledTaskProgressPreparation:
        """Prepare one current Scheduled progress action atomically."""
        async with self.session_manager() as session:
            resolution = await self._resolve_run_cycle(
                session,
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
            )
            if not resolution.scheduled:
                return ScheduledTaskProgressPreparation(
                    status="not_scheduled",
                    cycle_id=None,
                    state_revision=None,
                    reply_plans=(),
                    tracker=None,
                )
            record = resolution.record
            if record is None:
                return ScheduledTaskProgressPreparation(
                    status="inactive",
                    cycle_id=None,
                    state_revision=None,
                    reply_plans=(),
                    tracker=None,
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
            tracker_claim: _TrackerClaim | None = None
            if title is not None and tasks is not None:
                current = await self.cycle_repository.update_progress(
                    session,
                    record=current,
                    progress_title=title,
                    ordered_tasks=[task.title for task in tasks],
                )
                tracker_claim = await self._claim_tracker_effect(
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
            return ScheduledTaskProgressPreparation(
                status="prepared",
                cycle_id=current.state.cycle_id,
                state_revision=(
                    current.version
                    if tracker_claim is None
                    else tracker_claim.state_version
                ),
                reply_plans=tuple(reply_plans),
                tracker=None if tracker_claim is None else tracker_claim.effect,
            )

    async def admit_progress_effects(
        self,
        *,
        agent_id: str,
        session_id: str,
        run_id: str,
        state_revision: int,
        tracker_expected_desired_revision: int | None,
    ) -> ScheduledTaskProgressAdmission:
        """Revalidate one prepared progress action before external effects."""
        async with self.session_manager() as session:
            resolution = await self._resolve_run_cycle(
                session,
                agent_id=agent_id,
                session_id=session_id,
                run_id=run_id,
            )
            record = resolution.record
            if record is None:
                return ScheduledTaskProgressAdmission(
                    status="inactive",
                    tracker_current=False,
                )
            if record.version != state_revision:
                return ScheduledTaskProgressAdmission(
                    status="superseded",
                    tracker_current=False,
                )
            return ScheduledTaskProgressAdmission(
                status="admitted",
                tracker_current=(
                    tracker_expected_desired_revision is None
                    or record.state.tracker_desired_revision
                    == tracker_expected_desired_revision
                ),
            )

    async def settle_tracker(
        self,
        *,
        agent_id: str,
        session_id: str,
        cycle_id: str,
        effect: ScheduledTaskTrackerEffect,
        status: ExternalChannelWorkProjectionStatus,
        provider_message_key: str | None,
    ) -> bool:
        """Settle one Tracker outcome in a completed database transaction."""
        async with self.session_manager() as session:
            return await self.cycle_repository.settle_tracker_projection(
                session,
                agent_id=agent_id,
                session_id=session_id,
                cycle_id=cycle_id,
                expected_desired_revision=effect.expected_desired_revision,
                part_ordinal=effect.part_ordinal,
                status=status,
                provider_message_key=provider_message_key,
            )

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
    ) -> "_TrackerClaim | None":
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
            scheduled_task_schedule=render_scheduled_task_schedule(
                schedule_type=record.state.schedule_type,
                scheduled_at=record.state.scheduled_at,
                cron_expression=record.state.cron_expression,
                timezone=record.state.timezone,
                scheduled_for=record.state.scheduled_for,
            ).summary,
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
        return _TrackerClaim(
            effect=ScheduledTaskTrackerEffect(
                plan=plan,
                expected_desired_revision=desired_revision,
                part_ordinal=0,
            ),
            state_version=claimed.version,
        )


@dataclasses.dataclass(frozen=True)
class _TrackerClaim:
    """One Tracker effect plus its committed cycle-state version."""

    effect: ScheduledTaskTrackerEffect
    state_version: int
