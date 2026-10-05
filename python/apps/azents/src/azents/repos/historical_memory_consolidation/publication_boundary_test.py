"""Publication failures are normalized only at the repository boundary."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.historical_memory_publication import (
    ConsolidationPublicationUncertainError,
    ValidatedConsolidationOverview,
)
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.historical_memory_consolidation.publication import (
    ConsolidationPublicationOutcome,
    ConsolidationPublicationRepository,
)


@asynccontextmanager
async def _sessions() -> AsyncIterator[WriteSession]:
    async with AsyncSession() as session:
        yield ReadWriteSession(session)


@dataclass(frozen=True)
class _FailedPublication(ConsolidationPublicationRepository):
    error: BaseException

    async def _publish(
        self,
        principal: ConsolidationJobPrincipal,
        *,
        expected_draft_revision_id: str,
        expected_observation_epoch: int,
        overview: ValidatedConsolidationOverview,
    ) -> ConsolidationPublicationOutcome:
        del principal, expected_draft_revision_id, expected_observation_epoch, overview
        raise self.error


async def test_database_publication_failure_has_neutral_operation_error() -> None:
    """Only DBAPI failure carries uncertainty to the service inspection path."""
    original = OperationalError("database failure", None, RuntimeError("lost reply"))
    repository = _FailedPublication(
        session_manager=_sessions, read_session_manager=_sessions, error=original
    )
    with pytest.raises(ConsolidationPublicationUncertainError) as raised:
        await repository.publish(
            MagicMock(spec=ConsolidationJobPrincipal),
            expected_draft_revision_id="draft-1",
            expected_observation_epoch=1,
            overview=MagicMock(spec=ValidatedConsolidationOverview),
        )
    assert raised.value.__cause__ is original


@pytest.mark.parametrize("original", [RuntimeError("bug"), asyncio.CancelledError()])
async def test_publication_unrelated_failure_and_cancellation_propagate(
    original: BaseException,
) -> None:
    """Unrelated failure and cancellation never acquire commit recovery."""
    repository = _FailedPublication(
        session_manager=_sessions, read_session_manager=_sessions, error=original
    )
    with pytest.raises(type(original)) as raised:
        await repository.publish(
            MagicMock(spec=ConsolidationJobPrincipal),
            expected_draft_revision_id="draft-1",
            expected_observation_epoch=1,
            overview=MagicMock(spec=ValidatedConsolidationOverview),
        )
    assert raised.value is original
