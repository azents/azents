"""External Channel admission transaction tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelInteractionStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelInteraction,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionHandoff,
    SlackInteractionTriggerExpired,
)


class _SessionDouble:
    """Record interaction admission commits."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class _InteractionRepositoryDouble:
    """Record post-claim terminal interaction state without provider I/O."""

    def __init__(self) -> None:
        self.transitions: list[
            tuple[ExternalChannelInteractionStatus, str | None, str | None]
        ] = []

    async def transition_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        del session
        assert interaction_id == "interaction-1"
        self.transitions.append((status, error_kind, error_summary))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("callback_error", "expected_status", "expected_error_kind"),
    [
        (None, ExternalChannelInteractionStatus.COMPLETED, None),
        (
            SlackInteractionTriggerExpired(),
            ExternalChannelInteractionStatus.EXPIRED,
            "trigger_expired",
        ),
        (
            RuntimeError("provider ambiguity"),
            ExternalChannelInteractionStatus.FAILED,
            "provider_mutation_failed",
        ),
    ],
)
async def test_post_claim_mutation_terminalizes_once_without_trigger_retention(
    callback_error: Exception | None,
    expected_status: ExternalChannelInteractionStatus,
    expected_error_kind: str | None,
) -> None:
    """One already-committed mutation records one safe terminal state."""
    session = _SessionDouble()
    repository = _InteractionRepositoryDouble()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    handoff = ExternalChannelInteractionHandoff(
        interaction_id="interaction-1",
        handler="selector_open",
        provider_parent_channel_id=None,
        provider_thread_key=None,
        settings_metadata=None,
        settings_location=None,
        settings_response_mode=None,
        trigger_id="trigger-secret-must-not-persist",
    )

    async def callback(value: ExternalChannelInteractionHandoff) -> None:
        assert value is handoff
        if callback_error is not None:
            raise callback_error

    await ExternalChannelAdmissionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    ).run_interaction_provider_mutation(
        handoff=handoff,
        callback=callback,
    )

    assert repository.transitions == [
        (
            expected_status,
            expected_error_kind,
            (
                None
                if expected_error_kind is None
                else (
                    "Slack interaction trigger expired."
                    if expected_status is ExternalChannelInteractionStatus.EXPIRED
                    else "Slack interaction provider mutation failed."
                )
            ),
        )
    ]
    assert session.committed is True
    assert "trigger-secret" not in repr(handoff)


class _InteractionClaimRepositoryDouble:
    """Model one bounded PROCESSING interaction lease."""

    def __init__(self, interaction: ExternalChannelInteraction) -> None:
        self.interaction = interaction
        self.transitions: list[
            tuple[
                ExternalChannelInteractionStatus,
                str | None,
                datetime.datetime | None,
            ]
        ] = []

    async def lock_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        del session
        return self.interaction if interaction_id == self.interaction.id else None

    async def transition_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
        transitioned_at: datetime.datetime | None = None,
    ) -> ExternalChannelInteraction | None:
        del session, error_summary
        assert interaction_id == self.interaction.id
        self.transitions.append((status, error_kind, transitioned_at))
        self.interaction = self.interaction.model_copy(
            update={"status": status, "updated_at": transitioned_at}
        )
        return self.interaction


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("processing_age", "expected_abandoned"),
    [
        (datetime.timedelta(milliseconds=500), False),
        (datetime.timedelta(seconds=2), True),
    ],
)
async def test_processing_interaction_retry_terminalizes_only_stale_claim(
    processing_age: datetime.timedelta,
    expected_abandoned: bool,
) -> None:
    """A stale claim fails closed without replaying provider I/O."""
    now = datetime.datetime(2026, 7, 25, 12, tzinfo=datetime.UTC)
    interaction = ExternalChannelInteraction.model_construct(
        id="interaction-1",
        status=ExternalChannelInteractionStatus.PROCESSING,
        expires_at=now + datetime.timedelta(minutes=1),
        updated_at=now - processing_age,
    )
    repository = _InteractionClaimRepositoryDouble(interaction)
    session = _SessionDouble()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    claim = await ExternalChannelAdmissionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        provider_mutation_timeout=datetime.timedelta(milliseconds=500),
        processing_lease=datetime.timedelta(seconds=1),
    ).begin_interaction_provider_mutation(
        interaction_id=interaction.id,
        now=now,
    )

    assert claim is not None
    assert claim.claimed is False
    assert repository.transitions == (
        [
            (
                ExternalChannelInteractionStatus.FAILED,
                "processing_abandoned",
                now,
            )
        ]
        if expected_abandoned
        else []
    )
    assert session.committed is expected_abandoned


@pytest.mark.asyncio
async def test_provider_mutation_timeout_terminalizes_without_replay() -> None:
    """Provider work cannot outlive the lease window used for stale handling."""
    session = _SessionDouble()
    repository = _InteractionRepositoryDouble()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    async def callback(_: ExternalChannelInteractionHandoff) -> None:
        await asyncio.Event().wait()

    await ExternalChannelAdmissionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        provider_mutation_timeout=datetime.timedelta(milliseconds=1),
        processing_lease=datetime.timedelta(seconds=1),
    ).run_interaction_provider_mutation(
        handoff=ExternalChannelInteractionHandoff(
            interaction_id="interaction-1",
            handler="selector_open",
            provider_parent_channel_id=None,
            provider_thread_key=None,
            settings_metadata=None,
            settings_location=None,
            settings_response_mode=None,
        ),
        callback=callback,
    )

    assert repository.transitions == [
        (
            ExternalChannelInteractionStatus.FAILED,
            "processor_timeout",
            "Slack interaction processing timed out.",
        )
    ]
