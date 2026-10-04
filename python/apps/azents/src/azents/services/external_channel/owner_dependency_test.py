"""Production Channel Toolkit graphs construct explicit non-execution services."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from azcommon.di import Container, Dependency, DependencyOverrides
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.engine.tools.deps import get_external_channel_toolkit_provider
from azents.engine.tools.external_channel import ExternalChannelToolkitProvider
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.scheduled_task_cycle.progress import ScheduledTaskProgressRepository
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
    get_discord_delivery_client,
    get_slack_delivery_client,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.file_transfer import (
    ExternalChannelFileTransferService,
)
from azents.services.scheduled_task.channel import (
    ScheduledTaskChannelService,
    get_scheduled_task_channel_service,
)
from azents.worker.deps import (
    get_worker_external_channel_file_transfer_service,
    get_worker_external_channel_toolkit_provider,
)


@asynccontextmanager
async def _sessions() -> AsyncIterator[WriteSession]:
    async with AsyncSession() as session:
        yield ReadWriteSession(session)


def _session_manager() -> SessionManager[WriteSession]:
    return _sessions


def _config() -> Config:
    # No provider or transfer operation runs during constructor resolution.
    return Config.model_construct()


def _unused_external_dependency() -> None:
    """An intentionally disconnected collaborator, never invoked by this graph test."""
    return None


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk(child)


@pytest.mark.parametrize("entrypoint", ["engine", "worker", "scheduled"])
async def test_channel_owner_dependency_is_not_a_request_parameter(
    entrypoint: str,
) -> None:
    """Resolve production factories with explicit owner absence, never DI input."""
    call: Dependency[..., object]
    if entrypoint == "engine":
        call = get_external_channel_toolkit_provider
    elif entrypoint == "worker":
        call = get_worker_external_channel_toolkit_provider
    else:
        call = get_scheduled_task_channel_service
    graph = get_dependant(path="/", call=call)
    actions = [
        node
        for node in _walk(graph)
        if node.call
        in {
            ExternalChannelActionService,
            ExternalChannelActionService.create,
        }
    ]
    assert actions
    assert all(node.call == ExternalChannelActionService.create for node in actions)
    assert all(not node.query_params and not node.body_params for node in actions)
    assert all(node.call != ExternalChannelActionService for node in _walk(graph))
    overrides: DependencyOverrides = {
        get_session_manager: _session_manager,
        get_config: _config,
        get_external_channel_credentials_codec: _unused_external_dependency,
        get_slack_delivery_client: _unused_external_dependency,
        get_discord_delivery_client: _unused_external_dependency,
        ExchangeFileService: _unused_external_dependency,
        ExternalChannelFileTransferService: _unused_external_dependency,
        get_worker_external_channel_file_transfer_service: _unused_external_dependency,
        ScheduledTaskProgressRepository: _unused_external_dependency,
    }
    async with Container(dependency_overrides=overrides) as container:
        resolved = await container.solve(call)
    if isinstance(resolved, ExternalChannelToolkitProvider):
        service = resolved.service
        assert isinstance(
            resolved.scheduled_channel_service, ScheduledTaskChannelService
        )
    else:
        assert isinstance(resolved, ScheduledTaskChannelService)
        service = resolved.action_service
    assert isinstance(service, ExternalChannelActionService)
    assert isinstance(service.repository, ExternalChannelWorkRepository)
    assert service.execution_owner is None
    assert service.session_manager is _sessions
