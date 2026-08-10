"""Agent Runtime removal repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.models.agent_runtime_removal import (
    RDBAgentRuntimeRemovalOperation,
)

from .data import (
    AgentRuntimeRemovalCreateResult,
    AgentRuntimeRemovalOperation,
)


class AgentRuntimeRemovalRepository:
    """Repository for durable irreversible Runtime removal work."""

    async def create_or_get_active(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        workspace_id: str,
        requested_by_workspace_user_id: str,
        idempotency_key: str,
        expected_capability_version: int,
        committed_capability_version: int,
        agent_runtime_id: str | None,
        confirmed_at: datetime.datetime,
        destructive_scope_version: int,
        active_root_session_count: int,
        active_subagent_count: int,
        active_run_count: int,
        queued_runtime_action_count: int,
    ) -> AgentRuntimeRemovalCreateResult:
        """Create one active removal operation or return the conflicting one."""
        result = await session.execute(
            insert(RDBAgentRuntimeRemovalOperation)
            .values(
                id=uuid7().hex,
                agent_id=agent_id,
                workspace_id=workspace_id,
                requested_by_workspace_user_id=requested_by_workspace_user_id,
                idempotency_key=idempotency_key,
                expected_capability_version=expected_capability_version,
                committed_capability_version=committed_capability_version,
                agent_runtime_id=agent_runtime_id,
                confirmed_at=confirmed_at,
                destructive_scope_version=destructive_scope_version,
                active_root_session_count=active_root_session_count,
                active_subagent_count=active_subagent_count,
                active_run_count=active_run_count,
                queued_runtime_action_count=queued_runtime_action_count,
            )
            .on_conflict_do_nothing()
            .returning(RDBAgentRuntimeRemovalOperation)
        )
        row = result.scalar_one_or_none()
        idempotency_match = True
        if row is None:
            row = await session.scalar(
                sa.select(RDBAgentRuntimeRemovalOperation).where(
                    RDBAgentRuntimeRemovalOperation.agent_id == agent_id,
                    RDBAgentRuntimeRemovalOperation.idempotency_key == idempotency_key,
                )
            )
        if row is None:
            idempotency_match = False
            row = await session.scalar(
                sa.select(RDBAgentRuntimeRemovalOperation).where(
                    RDBAgentRuntimeRemovalOperation.agent_id == agent_id,
                    RDBAgentRuntimeRemovalOperation.status
                    != AgentRuntimeRemovalStatus.COMPLETED,
                )
            )
        if row is None:
            raise RuntimeError("Agent Runtime removal operation creation failed")
        await session.flush()
        return AgentRuntimeRemovalCreateResult(
            operation=self._build(row),
            idempotency_match=idempotency_match,
        )

    async def get_by_id(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> AgentRuntimeRemovalOperation | None:
        """Fetch one Runtime removal operation."""
        row = await session.get(RDBAgentRuntimeRemovalOperation, operation_id)
        return None if row is None else self._build(row)

    async def get_active_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntimeRemovalOperation | None:
        """Fetch the Agent's single non-terminal removal operation."""
        row = await session.scalar(
            sa.select(RDBAgentRuntimeRemovalOperation).where(
                RDBAgentRuntimeRemovalOperation.agent_id == agent_id,
                RDBAgentRuntimeRemovalOperation.status
                != AgentRuntimeRemovalStatus.COMPLETED,
            )
        )
        return None if row is None else self._build(row)

    async def lock_by_id(
        self,
        session: AsyncSession,
        operation_id: str,
    ) -> AgentRuntimeRemovalOperation | None:
        """Lock one removal operation for exact transition validation."""
        row = await session.scalar(
            sa.select(RDBAgentRuntimeRemovalOperation)
            .where(RDBAgentRuntimeRemovalOperation.id == operation_id)
            .with_for_update()
        )
        return None if row is None else self._build(row)

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentRuntimeRemovalOperation | None:
        """Claim one due removal operation with an expired-or-empty lease."""
        claimable = sa.or_(
            RDBAgentRuntimeRemovalOperation.status.in_(
                (
                    AgentRuntimeRemovalStatus.PENDING,
                    AgentRuntimeRemovalStatus.RETRY_WAIT,
                )
            ),
            sa.and_(
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_until < now,
            ),
        )
        candidate = (
            sa.select(RDBAgentRuntimeRemovalOperation.id)
            .where(
                claimable,
                sa.or_(
                    RDBAgentRuntimeRemovalOperation.next_attempt_at.is_(None),
                    RDBAgentRuntimeRemovalOperation.next_attempt_at <= now,
                ),
                sa.or_(
                    RDBAgentRuntimeRemovalOperation.lease_until.is_(None),
                    RDBAgentRuntimeRemovalOperation.lease_until < now,
                ),
            )
            .order_by(
                RDBAgentRuntimeRemovalOperation.created_at,
                RDBAgentRuntimeRemovalOperation.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(RDBAgentRuntimeRemovalOperation.id == candidate)
            .values(
                status=AgentRuntimeRemovalStatus.RUNNING,
                started_at=sa.func.coalesce(
                    RDBAgentRuntimeRemovalOperation.started_at,
                    now,
                ),
                attempt_count=RDBAgentRuntimeRemovalOperation.attempt_count + 1,
                lease_owner=lease_owner,
                lease_until=lease_until,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                updated_at=now,
            )
            .returning(RDBAgentRuntimeRemovalOperation)
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._build(row)

    async def set_stage(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        stage: AgentRuntimeRemovalStage,
        now: datetime.datetime,
    ) -> bool:
        """Advance the stage of an owned running operation."""
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
            )
            .values(stage=stage, updated_at=now)
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def record_cleanup_progress(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        expected_cursor_context_id: str | None,
        cursor_context_id: str | None,
        scanned_count: int,
        invalidated_count: int,
        completed: bool,
        now: datetime.datetime,
    ) -> bool:
        """Record monotonic bounded product-cleanup progress."""
        if scanned_count < 0 or invalidated_count < 0:
            raise ValueError("Removal cleanup progress cannot decrease")
        if invalidated_count > scanned_count:
            raise ValueError(
                "Invalidated cleanup count cannot exceed scanned cleanup count"
            )
        if cursor_context_id == expected_cursor_context_id:
            if not completed or scanned_count != 0 or invalidated_count != 0:
                raise ValueError("Removal cleanup cursor must advance")
        elif cursor_context_id is None or (
            expected_cursor_context_id is not None
            and cursor_context_id <= expected_cursor_context_id
        ):
            raise ValueError("Removal cleanup cursor cannot regress")
        expected_cursor = (
            RDBAgentRuntimeRemovalOperation.cleanup_cursor_context_id.is_(None)
            if expected_cursor_context_id is None
            else RDBAgentRuntimeRemovalOperation.cleanup_cursor_context_id
            == expected_cursor_context_id
        )
        values: dict[str, object | None] = {
            "cleanup_cursor_context_id": cursor_context_id,
            "cleanup_scanned_context_count": (
                RDBAgentRuntimeRemovalOperation.cleanup_scanned_context_count
                + scanned_count
            ),
            "cleanup_invalidated_context_count": (
                RDBAgentRuntimeRemovalOperation.cleanup_invalidated_context_count
                + invalidated_count
            ),
            "updated_at": now,
        }
        if completed:
            values["product_cleanup_completed_at"] = now
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
                RDBAgentRuntimeRemovalOperation.product_cleanup_completed_at.is_(None),
                expected_cursor,
            )
            .values(**values)
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def record_physical_delete_target(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        required: bool,
        target_generation: int | None,
        requested_at: datetime.datetime | None,
        now: datetime.datetime,
    ) -> bool:
        """Record the immutable physical-deletion requirement and target."""
        if required != (target_generation is not None and requested_at is not None):
            raise ValueError("Physical deletion target evidence is inconsistent")
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
                RDBAgentRuntimeRemovalOperation.physical_deletion_required.is_(None),
            )
            .values(
                physical_deletion_required=required,
                target_terminal_delete_generation=target_generation,
                physical_delete_requested_at=requested_at,
                updated_at=now,
            )
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def record_physical_delete_acknowledgement(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        acknowledgement_kind: RuntimeTerminalDeleteAcknowledgementKind,
        acknowledged_at: datetime.datetime,
    ) -> bool:
        """Record exact terminal physical-deletion evidence once."""
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
                RDBAgentRuntimeRemovalOperation.physical_deletion_required.is_(True),
                RDBAgentRuntimeRemovalOperation.target_terminal_delete_generation.is_not(
                    None
                ),
                RDBAgentRuntimeRemovalOperation.physical_delete_acknowledged_at.is_(
                    None
                ),
                RDBAgentRuntimeRemovalOperation.physical_delete_acknowledgement_kind.is_(
                    None
                ),
            )
            .values(
                physical_delete_acknowledgement_kind=acknowledgement_kind,
                physical_delete_acknowledged_at=acknowledged_at,
                updated_at=acknowledged_at,
            )
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Release an owned operation into bounded retry wait."""
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
            )
            .values(
                status=AgentRuntimeRemovalStatus.RETRY_WAIT,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                last_error_kind=error_kind[:120],
                last_error_summary=error_summary[:500],
                updated_at=now,
            )
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_completed(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Complete an owned operation and release its lease."""
        result = await session.execute(
            sa.update(RDBAgentRuntimeRemovalOperation)
            .where(
                RDBAgentRuntimeRemovalOperation.id == operation_id,
                RDBAgentRuntimeRemovalOperation.status
                == AgentRuntimeRemovalStatus.RUNNING,
                RDBAgentRuntimeRemovalOperation.lease_owner == lease_owner,
                RDBAgentRuntimeRemovalOperation.stage
                == AgentRuntimeRemovalStage.FINALIZING,
                RDBAgentRuntimeRemovalOperation.product_cleanup_completed_at.is_not(
                    None
                ),
                RDBAgentRuntimeRemovalOperation.physical_deletion_required.is_not(None),
                sa.or_(
                    RDBAgentRuntimeRemovalOperation.physical_deletion_required.is_(
                        False
                    ),
                    RDBAgentRuntimeRemovalOperation.physical_delete_acknowledged_at.is_not(
                        None
                    ),
                ),
            )
            .values(
                status=AgentRuntimeRemovalStatus.COMPLETED,
                stage=AgentRuntimeRemovalStage.COMPLETED,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                completed_at=now,
                updated_at=now,
            )
            .returning(RDBAgentRuntimeRemovalOperation.id)
        )
        return result.scalar_one_or_none() is not None

    def _build(
        self,
        row: RDBAgentRuntimeRemovalOperation,
    ) -> AgentRuntimeRemovalOperation:
        """Convert a database row to a domain model."""
        return AgentRuntimeRemovalOperation(
            id=row.id,
            agent_id=row.agent_id,
            workspace_id=row.workspace_id,
            requested_by_workspace_user_id=row.requested_by_workspace_user_id,
            idempotency_key=row.idempotency_key,
            expected_capability_version=row.expected_capability_version,
            committed_capability_version=row.committed_capability_version,
            agent_runtime_id=row.agent_runtime_id,
            status=row.status,
            stage=row.stage,
            confirmed_at=row.confirmed_at,
            destructive_scope_version=row.destructive_scope_version,
            active_root_session_count=row.active_root_session_count,
            active_subagent_count=row.active_subagent_count,
            active_run_count=row.active_run_count,
            queued_runtime_action_count=row.queued_runtime_action_count,
            cleanup_cursor_context_id=row.cleanup_cursor_context_id,
            cleanup_scanned_context_count=row.cleanup_scanned_context_count,
            cleanup_invalidated_context_count=row.cleanup_invalidated_context_count,
            product_cleanup_completed_at=row.product_cleanup_completed_at,
            physical_deletion_required=row.physical_deletion_required,
            target_terminal_delete_generation=(row.target_terminal_delete_generation),
            physical_delete_requested_at=row.physical_delete_requested_at,
            physical_delete_acknowledgement_kind=(
                row.physical_delete_acknowledgement_kind
            ),
            physical_delete_acknowledged_at=row.physical_delete_acknowledged_at,
            attempt_count=row.attempt_count,
            lease_owner=row.lease_owner,
            lease_until=row.lease_until,
            next_attempt_at=row.next_attempt_at,
            last_error_kind=row.last_error_kind,
            last_error_summary=row.last_error_summary,
            started_at=row.started_at,
            completed_at=row.completed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
