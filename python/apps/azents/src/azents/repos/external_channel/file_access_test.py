"""Completed External Channel file-access repository operation tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelProvider
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.external_channel.file_access import (
    ExternalChannelFileAccessRepository,
)
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ExternalChannelFileAccessTarget


async def test_active_target_read_completes_its_database_transaction() -> None:
    """Return a detached target only after the repository session closes."""
    target = ExternalChannelFileAccessTarget(
        binding_id="binding-1",
        connection_id="connection-1",
        resource_id="resource-1",
        provider=ExternalChannelProvider.SLACK,
        encrypted_credentials="ciphertext",
        provider_tenant_id="tenant-1",
        capabilities={"download_files": True},
        resource_labels={"channel_id": "channel-1"},
    )
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    work_repository = AsyncMock(spec=ExternalChannelWorkRepository)

    async def load_target(
        current_session: WriteSession,
        *,
        session_id: str,
        agent_id: str,
        binding_id: str,
    ) -> ExternalChannelFileAccessTarget:
        assert transaction_active
        assert current_session is session
        assert (session_id, agent_id, binding_id) == (
            "session-1",
            "agent-1",
            "binding-1",
        )
        return target

    work_repository.get_active_file_access_target.side_effect = load_target
    repository = ExternalChannelFileAccessRepository(
        work_repository=work_repository,
        session_manager=session_manager,
    )

    result = await repository.get_active_target(
        session_id="session-1",
        agent_id="agent-1",
        binding_id="binding-1",
    )

    assert result == target
    assert not transaction_active
