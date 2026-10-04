"""PostgreSQL-derived preflight and replay for the Team Session cutover."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.config import Config
from azents.core.deps import get_appctx
from azents.repos.session_execution.cutover_replay_data import (
    TeamSessionCutoverReplayInvariantFailure,
    TeamSessionCutoverReplayReport,
)
from azents.repos.session_execution.cutover_replay_operations import (
    TeamSessionCutoverReplayOperationsRepository,
)
from azents.utils.appctx import AppContext
from azents.worker.deps import get_worker_broker, get_worker_id

SessionBrokerProvider = Callable[[], Awaitable[SessionBroker]]
_FENCE_TIMEOUT_SECONDS = 30 * 60
_BROKER_OPERATION_TIMEOUT_SECONDS = 5 * 60


def get_team_session_cutover_broker_provider(
    appctx: Annotated[AppContext[Config], Depends(get_appctx)],
    worker_id: Annotated[str, Depends(get_worker_id)],
) -> SessionBrokerProvider:
    """Return a lazy broker dependency so preflight performs no Redis I/O."""

    async def provide_broker() -> SessionBroker:
        return await get_worker_broker(appctx, worker_id)

    return provide_broker


class TeamSessionCutoverReplayBarrierLostError(RuntimeError):
    """The replay process lost its Redis ownership-acquisition barrier."""


@dataclasses.dataclass
class TeamSessionCutoverReplayService:
    """Reconstruct Session wake-ups from durable PostgreSQL work state."""

    operations: Annotated[
        TeamSessionCutoverReplayOperationsRepository,
        Depends(TeamSessionCutoverReplayOperationsRepository),
    ]
    broker_provider: Annotated[
        SessionBrokerProvider,
        Depends(get_team_session_cutover_broker_provider),
    ]

    async def preflight(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Validate one bounded PostgreSQL-derived replay batch without broker I/O."""
        preflight_batch = await self.operations.preflight_batch(
            batch_size=batch_size,
            after_session_id=after_session_id,
        )
        return preflight_batch.report

    async def replay(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Discard broker state and emit pure wake-ups for a valid durable batch."""
        preflight_batch = await self.operations.preflight_batch(
            batch_size=batch_size,
            after_session_id=after_session_id,
        )
        report = preflight_batch.report
        if report.invariant_failures:
            raise TeamSessionCutoverReplayInvariantFailure(
                invariant_failures=report.invariant_failures
            )

        broker = await self.broker_provider()
        session_ids = tuple(
            candidate.session_id for candidate in preflight_batch.valid_candidates
        )
        async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
            barrier_token = await broker.acquire_cutover_replay_barrier(session_ids)
        try:
            async with asyncio.timeout(_FENCE_TIMEOUT_SECONDS):
                await self.operations.fence_replay_batch(
                    preflight_batch.valid_candidates
                )
            for candidate in preflight_batch.valid_candidates:
                await _renew_barrier(
                    broker=broker,
                    session_ids=session_ids,
                    token=barrier_token,
                )
                async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                    await broker.purge_session_state(candidate.session_id)
                await _renew_barrier(
                    broker=broker,
                    session_ids=session_ids,
                    token=barrier_token,
                )
                async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                    await broker.send_message(
                        SessionWakeUp(session_id=candidate.session_id)
                    )
        finally:
            async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
                await broker.release_cutover_replay_barrier(
                    session_ids,
                    barrier_token,
                )

        return dataclasses.replace(
            report,
            replayed_sessions=len(preflight_batch.valid_candidates),
        )


async def _renew_barrier(
    *,
    broker: SessionBroker,
    session_ids: tuple[str, ...],
    token: str,
) -> None:
    """Renew the exact cutover barrier or abort before another operation."""
    async with asyncio.timeout(_BROKER_OPERATION_TIMEOUT_SECONDS):
        renewed = await broker.renew_cutover_replay_barrier(
            session_ids,
            token,
        )
    if not renewed:
        raise TeamSessionCutoverReplayBarrierLostError(
            "Team Session cutover replay barrier was lost"
        )
