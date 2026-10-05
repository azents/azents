"""Exact job authority and short database-time ownership fences."""

import asyncio
import datetime
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from psycopg.errors import (
    DeadlockDetected,
    LockNotAvailable,
    QueryCanceled,
    SerializationFailure,
)
from sqlalchemy.exc import OperationalError

from azents.core.enums import AgentLifecycleStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationAttemptState,
    ConsolidationJobPrincipal,
    ConsolidationUnitKey,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationAttempt,
    RDBConsolidationUnit,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession


class ConsolidationAuthorityError(PermissionError):
    """Unavailable exact scope or stale execution owner, with no peer disclosure."""


class ConsolidationAuthorityBusyError(ConsolidationAuthorityError):
    """Current authority could not be confirmed while another DB writer held it."""


class ConsolidationDeadlineError(ConsolidationAuthorityError):
    """A protected database operation exceeded its lease/attempt time boundary."""


@asynccontextmanager
async def consolidation_session(
    manager: SessionManager[WriteSession],
) -> AsyncIterator[WriteSession]:
    """Complete rollback before normalizing only expected NOWAIT contention."""
    try:
        async with manager() as session:
            yield session
    except OperationalError as error:
        if isinstance(error.orig, QueryCanceled):
            raise ConsolidationDeadlineError(
                "Consolidation database deadline was exceeded."
            ) from None
        if not isinstance(
            error.orig, LockNotAvailable | DeadlockDetected | SerializationFailure
        ):
            raise
        raise ConsolidationAuthorityBusyError(
            "Consolidation authority is temporarily unavailable."
        ) from None


@asynccontextmanager
async def consolidation_read_session(
    manager: SessionManager[ReadSession],
) -> AsyncIterator[ReadSession]:
    """Complete independent reads while retaining existing deadline failures."""
    try:
        async with manager() as session:
            yield session
    except OperationalError as error:
        if not isinstance(error.orig, QueryCanceled):
            raise
        raise ConsolidationDeadlineError(
            "Consolidation database deadline was exceeded."
        ) from None


@dataclass(frozen=True)
class LockedConsolidationOwner:
    """Repository-local rows held only during a database operation."""

    unit: RDBConsolidationUnit
    attempt: RDBConsolidationAttempt
    database_now: datetime.datetime


@dataclass(frozen=True)
class ConsolidationJobSession:
    """A fenced database transaction with an enforceable operation deadline."""

    session: WriteSession
    owner: LockedConsolidationOwner


@dataclass(frozen=True)
class ObservedConsolidationTime:
    """Unfenced time observation; it cannot authorize any model or DB mutation."""

    lease_until: datetime.datetime
    deadline_at: datetime.datetime
    database_now: datetime.datetime


async def observe_operation_time(
    session: ReadSession, principal: ConsolidationJobPrincipal
) -> ObservedConsolidationTime:
    """Read a conservative time bound, never an authorization to mutate."""
    limits = (
        await session.read_session.execute(
            sa.select(
                RDBConsolidationUnit.lease_until,
                RDBConsolidationAttempt.deadline_at,
            )
            .join(
                RDBConsolidationAttempt,
                RDBConsolidationAttempt.id == RDBConsolidationUnit.active_attempt_id,
            )
            .where(
                unit_predicate(principal.unit),
                RDBConsolidationUnit.owner_generation == principal.owner_generation,
                RDBConsolidationUnit.owner_token == principal.owner_token,
                RDBConsolidationUnit.active_attempt_id == principal.attempt_id,
                RDBConsolidationAttempt.unit_id == RDBConsolidationUnit.id,
                RDBConsolidationAttempt.owner_generation == principal.owner_generation,
                RDBConsolidationAttempt.owner_token == principal.owner_token,
                RDBConsolidationAttempt.state == ConsolidationAttemptState.RUNNING,
            )
        )
    ).one_or_none()
    if limits is None or limits.lease_until is None:
        raise ConsolidationAuthorityError("Consolidation owner is no longer current.")
    now = await database_now(session)
    return ObservedConsolidationTime(limits.lease_until, limits.deadline_at, now)


async def observe_attempt_seconds(
    session: ReadSession, principal: ConsolidationJobPrincipal
) -> float:
    """Capture only the immutable attempt cutoff across contention retries."""
    time = await observe_operation_time(session, principal)
    remaining = (time.deadline_at - time.database_now).total_seconds()
    if remaining <= 0:
        raise ConsolidationDeadlineError(
            "Consolidation database deadline was exceeded."
        )
    return remaining


async def observe_operation_seconds(
    session: ReadSession, principal: ConsolidationJobPrincipal
) -> float:
    """Bound one transaction by the current lease and immutable attempt cutoff."""
    time = await observe_operation_time(session, principal)
    remaining = (
        min(time.lease_until, time.deadline_at) - time.database_now
    ).total_seconds()
    if remaining <= 0:
        raise ConsolidationDeadlineError(
            "Consolidation database deadline was exceeded."
        )
    return remaining


async def install_statement_deadline(session: WriteSession, seconds: float) -> None:
    """Bound SQL before the first authority or owner lock can wait."""
    await session.write_session.execute(
        sa.select(
            sa.func.set_config(
                "statement_timeout",
                str(max(1, math.ceil(seconds * 1000))),
                True,
            )
        )
    )


@asynccontextmanager
async def consolidation_job_session(
    manager: SessionManager[WriteSession], principal: ConsolidationJobPrincipal
) -> AsyncIterator[ConsolidationJobSession]:
    """Bound admission and all DB work by the approved lease and attempt deadline."""
    timeout = asyncio.timeout(None)
    try:
        async with timeout:
            async with consolidation_session(manager) as session:
                remaining = await observe_operation_seconds(session, principal)
                timeout.reschedule(asyncio.get_running_loop().time() + remaining)
                await install_statement_deadline(session, remaining)
                owner = await lock_job_owner(session, principal)
                if owner.unit.lease_until is None:
                    raise ConsolidationAuthorityError(
                        "Consolidation owner is no longer current."
                    )
                now = await database_now(session)
                remaining = (
                    min(owner.unit.lease_until, owner.attempt.deadline_at) - now
                ).total_seconds()
                if remaining <= 0:
                    raise ConsolidationDeadlineError(
                        "Consolidation database deadline was exceeded."
                    )
                current_deadline = timeout.when()
                if current_deadline is None:
                    raise RuntimeError("Consolidation operation deadline is missing.")
                timeout.reschedule(
                    min(
                        current_deadline,
                        asyncio.get_running_loop().time() + remaining,
                    )
                )
                await install_statement_deadline(session, remaining)
                yield ConsolidationJobSession(session, owner)
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        if not timeout.expired():
            raise
        raise ConsolidationDeadlineError(
            "Consolidation database deadline was exceeded."
        ) from None


def unit_predicate(key: ConsolidationUnitKey) -> sa.ColumnElement[bool]:
    """Match every component of an exact independent unit."""
    return sa.and_(
        RDBConsolidationUnit.agent_id == key.agent_id,
        RDBConsolidationUnit.workspace_id == key.workspace_id,
        RDBConsolidationUnit.scope == key.scope,
        RDBConsolidationUnit.associated_user_id.is_not_distinct_from(
            key.associated_user_id
        ),
    )


async def lock_unit_authority(
    session: WriteSession, key: ConsolidationUnitKey
) -> str | None:
    """Protect current Agent eligibility and personal grant from concurrent loss.

    Short nonwaiting shared locks avoid inversion with existing source lifecycle
    writers. Lock contention is an ordinary retryable database failure, never a
    reason to assume authority. No foreground identity is created or consulted.
    """
    agent = await session.write_session.scalar(
        sa.select(RDBAgent)
        .where(
            RDBAgent.id == key.agent_id,
            RDBAgent.workspace_id == key.workspace_id,
            RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            RDBAgent.memory_enabled.is_(True),
        )
        .with_for_update(read=True, nowait=True)
    )
    if agent is None:
        raise ConsolidationAuthorityError("Consolidation scope is unavailable.")
    if key.associated_user_id is None:
        return None
    grant = await session.write_session.scalar(
        sa.select(RDBWorkspaceUser.memory_grant_identity)
        .where(
            RDBWorkspaceUser.workspace_id == key.workspace_id,
            RDBWorkspaceUser.user_id == key.associated_user_id,
        )
        .with_for_update(read=True, nowait=True)
    )
    if grant is None:
        raise ConsolidationAuthorityError("Consolidation scope is unavailable.")
    return grant


async def database_now(session: ReadSession) -> datetime.datetime:
    """Sample database wall time after lock acquisition, not transaction start."""
    value = await session.read_session.scalar(sa.select(sa.func.clock_timestamp()))
    if not isinstance(value, datetime.datetime):
        raise TypeError("Database clock did not return an aware timestamp.")
    return value


async def require_commit_owner(
    session: ReadSession, owner: LockedConsolidationOwner
) -> None:
    """Reject transactions crossing the deadline or lease while doing DB work."""
    now = await database_now(session)
    if (
        owner.unit.lease_until is None
        or owner.unit.lease_until <= now
        or owner.attempt.deadline_at <= now
    ):
        raise ConsolidationAuthorityError("Consolidation commit owner expired.")


async def lock_job_owner(
    session: WriteSession, principal: ConsolidationJobPrincipal
) -> LockedConsolidationOwner:
    """Reauthorize and fence every operation, including replay and late results."""
    grant = await lock_unit_authority(session, principal.unit)
    unit = await session.write_session.scalar(
        sa.select(RDBConsolidationUnit)
        .where(unit_predicate(principal.unit))
        .with_for_update()
    )
    now = await database_now(session)
    if (
        unit is None
        or unit.owner_generation != principal.owner_generation
        or unit.owner_token != principal.owner_token
        or unit.active_attempt_id != principal.attempt_id
        or unit.lease_until is None
        or unit.lease_until <= now
    ):
        raise ConsolidationAuthorityError("Consolidation owner is no longer current.")
    attempt = await session.write_session.get(
        RDBConsolidationAttempt, principal.attempt_id
    )
    if (
        attempt is None
        or attempt.unit_id != unit.id
        or attempt.owner_generation != principal.owner_generation
        or attempt.owner_token != principal.owner_token
        or attempt.state is not ConsolidationAttemptState.RUNNING
        or attempt.deadline_at <= now
        or attempt.membership_grant_id != grant
    ):
        raise ConsolidationAuthorityError("Consolidation attempt is unavailable.")
    return LockedConsolidationOwner(unit, attempt, now)
