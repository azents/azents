"""Repository primitives for common execution records and dependent writes."""

import datetime

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from azents.core.agent import AgentModelSelection, SelectableModelSettings
from azents.core.enums import AgentSessionRunState, AgentSessionStatus
from azents.core.inference_profile import (
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)
from azents.core.session_execution_data import SessionExecutionRecord
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.session_capabilities import ReadSession, WriteSession


class SessionExecutionRecordRepository:
    """Read and fence common Session state without public Conversation joins."""

    async def claim_owner_generation(
        self, session: WriteSession, session_id: str
    ) -> int:
        """Advance ownership only while the common lifecycle root remains active."""
        current = await self.get_by_id(session, session_id)
        if current is None:
            raise ValueError("AgentSession not found")
        root_id = current.lifecycle_root_session_id or current.id
        root = (
            await session.read_session.execute(
                sa.select(
                    RDBAgentSession.status,
                    RDBAgentSession.agent_id,
                    RDBAgentSession.workspace_id,
                    RDBAgentSession.lifecycle_root_session_id,
                ).where(RDBAgentSession.id == root_id)
            )
        ).one_or_none()
        if root is None or root.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("Root AgentSession is not active")
        if (
            root.agent_id != current.agent_id
            or root.workspace_id != current.workspace_id
            or root.lifecycle_root_session_id is not None
        ):
            raise ValueError("Root AgentSession authority mismatch")
        generation = await session.write_session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(owner_generation=RDBAgentSession.owner_generation + 1)
            .returning(RDBAgentSession.owner_generation)
        )
        if generation is None:
            raise ValueError("AgentSession not found")
        return generation

    async def mark_running(self, session: WriteSession, session_id: str) -> None:
        """Mark active common execution as running without a public profile."""
        updated_id = await session.write_session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .values(
                run_state=AgentSessionRunState.RUNNING,
                run_heartbeat_at=sa.func.now(),
            )
            .returning(RDBAgentSession.id)
        )
        if updated_id is None:
            raise ValueError("Active AgentSession not found")
        await session.write_session.flush()

    async def mark_idle(self, session: WriteSession, session_id: str) -> None:
        """Finish common execution and clear processed stop intent atomically."""
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(
                run_state=AgentSessionRunState.IDLE,
                stop_requested_at=None,
                stop_requester_user_id=None,
                stop_request_id=None,
            )
        )
        await session.write_session.flush()

    async def heartbeat_running(self, session: WriteSession, session_id: str) -> None:
        """Renew durable heartbeat only for running execution."""
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(run_heartbeat_at=sa.func.now())
        )
        await session.write_session.flush()

    async def claim_lifecycle_start(
        self,
        session: WriteSession,
        session_id: str,
        *,
        now: datetime.datetime,
    ) -> bool:
        """Claim common execution's one-time lifecycle admission marker."""
        claimed_id = await session.write_session.scalar(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.lifecycle_started_at.is_(None),
            )
            .values(lifecycle_started_at=now)
            .returning(RDBAgentSession.id)
        )
        await session.write_session.flush()
        return claimed_id is not None

    async def has_stop_request(self, session: ReadSession, session_id: str) -> bool:
        """Observe durable stop intent for any common execution identity."""
        return (
            await session.read_session.scalar(
                sa.select(RDBAgentSession.id).where(
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.stop_requested_at.is_not(None),
                )
            )
        ) is not None

    async def get_by_id(
        self, session: ReadSession, session_id: str
    ) -> SessionExecutionRecord | None:
        current = await session.read_session.scalar(
            sa.select(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .where(RDBAgentSession.id == session_id)
        )
        return None if current is None else self.build(current)

    async def fence_owner(
        self, session: WriteSession, owner: SessionExecutionOwner
    ) -> SessionExecutionRecord | None:
        result = await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == owner.session_id,
                RDBAgentSession.owner_generation == owner.owner_generation,
            )
            .values(
                owner_generation=RDBAgentSession.owner_generation,
                updated_at=RDBAgentSession.updated_at,
            )
            .returning(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .execution_options(populate_existing=True)
        )
        current = result.scalar_one_or_none()
        return None if current is None else self.build(current)

    async def lock_compaction_plan_if_current(
        self,
        session: WriteSession,
        *,
        session_id: str,
        expected_head_event_id: str | None,
        expected_tail_event_id: str,
    ) -> bool:
        current = await session.write_session.scalar(
            sa.select(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .where(RDBAgentSession.id == session_id)
            .with_for_update(of=RDBAgentSession)
        )
        if current is None:
            raise ValueError("Execution Session not found")
        tail = await session.write_session.scalar(
            sa.select(RDBEvent.id)
            .where(RDBEvent.session_id == session_id, RDBEvent.reverted.is_(False))
            .order_by(RDBEvent.id.desc())
            .limit(1)
        )
        return (
            current.model_input_head_event_id == expected_head_event_id
            and tail == expected_tail_event_id
        )

    async def move_model_input_head(
        self, session: WriteSession, session_id: str, event_id: str
    ) -> SessionExecutionRecord:
        existing = await session.write_session.scalar(
            sa.select(RDBEvent.id).where(
                RDBEvent.session_id == session_id, RDBEvent.id == event_id
            )
        )
        if existing is None:
            raise ValueError("Model input head event not found in session")
        current = await session.write_session.scalar(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(model_input_head_event_id=event_id)
            .returning(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .execution_options(populate_existing=True)
        )
        if current is None:
            raise ValueError("Execution Session not found")
        return self.build(current)

    @staticmethod
    def build(rdb: RDBAgentSession) -> SessionExecutionRecord:
        """Decode the shared execution state without Conversation placeholders."""
        applied_inference_profile = None
        if rdb.applied_model_target_label is not None:
            applied_inference_profile = SessionAppliedInferenceProfile(
                model_target_label=rdb.applied_model_target_label,
                reasoning_effort=rdb.applied_reasoning_effort,
                enabled_execution_options=rdb.applied_enabled_execution_options,
            )
        inference_state: SessionInferenceState | None = None
        if rdb.current_model_target_label is not None:
            if (
                rdb.current_model_selection is None
                or rdb.current_model_settings is None
                or rdb.current_effective_context_window_tokens is None
                or rdb.current_effective_auto_compaction_threshold_tokens is None
                or rdb.current_inference_resolved_at is None
            ):
                raise ValueError("AgentSession has incomplete inference state")
            inference_state = SessionInferenceState(
                model_target_label=rdb.current_model_target_label,
                model_selection=AgentModelSelection.model_validate(
                    rdb.current_model_selection
                ),
                model_settings=SelectableModelSettings.model_validate(
                    rdb.current_model_settings
                ),
                reasoning_effort=rdb.current_reasoning_effort,
                enabled_execution_options=rdb.current_enabled_execution_options,
                effective_context_window_tokens=(
                    rdb.current_effective_context_window_tokens
                ),
                effective_auto_compaction_threshold_tokens=(
                    rdb.current_effective_auto_compaction_threshold_tokens
                ),
                resolved_at=rdb.current_inference_resolved_at,
            )
        return SessionExecutionRecord(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_id=rdb.agent_id,
            inference_state=inference_state,
            applied_inference_profile=applied_inference_profile,
            applied_profile_generation=rdb.applied_profile_generation,
            status=rdb.status,
            start_reason=rdb.start_reason,
            last_activity_at=rdb.last_activity_at,
            end_reason=rdb.end_reason,
            model_input_head_event_id=rdb.model_input_head_event_id,
            model_file_gc_cursor_event_id=rdb.model_file_gc_cursor_event_id,
            started_at=rdb.started_at,
            lifecycle_started_at=rdb.lifecycle_started_at,
            run_state=rdb.run_state,
            run_heartbeat_at=rdb.run_heartbeat_at,
            owner_generation=rdb.owner_generation,
            stop_requested_at=rdb.stop_requested_at,
            stop_requester_user_id=rdb.stop_requester_user_id,
            stop_request_id=rdb.stop_request_id,
            archived_at=rdb.archived_at,
            purge_after=rdb.purge_after,
            archive_policy_revision=rdb.archive_policy_revision,
            archive_retention_days_snapshot=rdb.archive_retention_days_snapshot,
            ended_at=rdb.ended_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
            lifecycle_root_session_id=rdb.lifecycle_root_session_id,
            model_file_gc_updated_at=rdb.model_file_gc_updated_at,
        )
