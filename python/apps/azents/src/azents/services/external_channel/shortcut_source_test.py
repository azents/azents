"""Shortcut source readiness materialization tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)

_NOW = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)


class _Session:
    def __init__(self) -> None:
        self.commit_count = 0

    async def commit(self) -> None:
        self.commit_count += 1


class _Repository:
    """Narrow double: any execution primitive would be an unexpected attribute."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.admission: object | None = None

    async def get_event_by_provider_identity(
        self, *args: object, **kwargs: object
    ) -> object:
        del args, kwargs
        self.calls.append("event")
        return SimpleNamespace(
            id="event-1",
            connection_id="connection-1",
            event_type="app_mention",
            provider_tenant_id="T-1",
            envelope={
                "event": {
                    "type": "app_mention",
                    "channel": "C-1",
                    "user": "U-source",
                    "ts": "100.0001",
                    "thread_ts": "100.0001",
                    "text": "source text",
                }
            },
        )

    async def lock_interaction(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("interaction")
        return SimpleNamespace(
            id="interaction-1",
            connection_id="connection-1",
            interaction_type=ExternalChannelInteractionType.SHORTCUT,
            principal_id="principal-actor",
        )

    async def lock_connection_for_routing(
        self, *args: object, **kwargs: object
    ) -> object:
        del args, kwargs
        self.calls.append("connection")
        return SimpleNamespace(
            id="connection-1",
            app_mode=ExternalChannelAppMode.MULTI,
            provider=ExternalChannelProvider.SLACK,
        )

    async def create_resource_idempotent(
        self, *args: object, **kwargs: object
    ) -> object:
        del args, kwargs
        self.calls.append("resource_create")
        return SimpleNamespace(id="resource-1")

    async def lock_resource(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.calls.append("resource_lock")
        return SimpleNamespace(
            id="resource-1",
            status=ExternalChannelResourceStatus.ACTIVE,
        )

    async def lock_active_binding_by_resource(
        self, *args: object, **kwargs: object
    ) -> None:
        del args, kwargs
        self.calls.append("binding")
        return None

    async def lock_open_conversation_admission(
        self, *args: object, **kwargs: object
    ) -> object | None:
        del args, kwargs
        self.calls.append("admission_lock")
        return self.admission

    async def create_principal_idempotent(
        self, *args: object, **kwargs: object
    ) -> object:
        del args, kwargs
        self.calls.append("principal")
        return SimpleNamespace(id="principal-source")

    async def create_message_idempotent(
        self, session: object, create: object
    ) -> object:
        del session
        self.calls.append("message")
        assert cast(Any, create).principal_id == "principal-source"
        return SimpleNamespace(id="message-1")

    async def create_message_revision_idempotent(
        self, session: object, create: object
    ) -> object:
        del session
        self.calls.append("revision")
        assert cast(Any, create).source_event_id == "event-1"
        return SimpleNamespace(id="revision-1")

    async def apply_message_revision(self, *args: object, **kwargs: object) -> object:
        del args
        self.calls.append("apply")
        assert kwargs["principal_id"] == "principal-source"
        return SimpleNamespace(id="message-1")

    async def create_conversation_admission_idempotent(
        self, session: object, create: object
    ) -> object:
        del session
        self.calls.append("admission_create")
        assert cast(Any, create).initiating_principal_id == "principal-actor"
        assert cast(Any, create).source_message_id == "message-1"
        self.admission = SimpleNamespace(id="admission-1")
        return self.admission


def _source_event() -> ExternalChannelEventCreate:
    return ExternalChannelEventCreate(
        connection_id="connection-1",
        provider_event_id="shortcut-http-1",
        transport_envelope_id=None,
        event_type="app_mention",
        provider_app_id="A-1",
        provider_tenant_id="T-1",
        provider_enterprise_id=None,
        resource_correlation_key="C-1:100.0001",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=_NOW,
        received_at=_NOW,
    )


def _service(
    session: _Session, repository: _Repository
) -> ExternalChannelShortcutSourceService:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return ExternalChannelShortcutSourceService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    )


@pytest.mark.asyncio
async def test_shortcut_source_is_committed_route_neutral_before_modal_claim() -> None:
    session = _Session()
    repository = _Repository()

    result = await _service(session, repository).ensure(
        shortcut_source_event=_source_event(),
        interaction_id="interaction-1",
        now=_NOW,
    )

    assert result.admission is not None
    assert result.admission.id == "admission-1"
    assert session.commit_count == 1
    assert repository.calls == [
        "event",
        "interaction",
        "connection",
        "resource_create",
        "resource_lock",
        "binding",
        "admission_lock",
        "principal",
        "message",
        "revision",
        "apply",
        "admission_create",
    ]


@pytest.mark.asyncio
async def test_shortcut_source_retry_reuses_admission_without_execution_effects() -> (
    None
):
    session = _Session()
    repository = _Repository()
    service = _service(session, repository)

    first = await service.ensure(
        shortcut_source_event=_source_event(), interaction_id="interaction-1", now=_NOW
    )
    second = await service.ensure(
        shortcut_source_event=_source_event(), interaction_id="interaction-1", now=_NOW
    )

    assert first.admission is second.admission
    assert repository.calls.count("admission_create") == 1
    assert session.commit_count == 2
    assert not any(
        forbidden in " ".join(repository.calls)
        for forbidden in (
            "pending_context",
            "access_request",
            "binding_create",
            "session",
            "mailbox_item",
            "wake",
        )
    )
