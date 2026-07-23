"""Runtime Runner authentication service tests."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_runner_credential import (
    RuntimeRunnerCredentialInvalid,
    RuntimeRunnerCredentialVerifier,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.services.runtime_runner_auth.service import (
    RuntimeRunnerAuthenticationService,
)


class _FakeRuntimeRepository:
    def __init__(self, runtime: AgentRuntime | None) -> None:
        self.runtime = runtime

    async def get_by_id(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> AgentRuntime | None:
        del session
        if self.runtime is None or self.runtime.id != runtime_id:
            return None
        return self.runtime


def _runtime(*, desired_generation: int) -> AgentRuntime:
    now = datetime.datetime.now(datetime.UTC)
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        desired_generation=desired_generation,
        created_at=now,
        updated_at=now,
    )


def _service(runtime: AgentRuntime | None) -> RuntimeRunnerAuthenticationService:
    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    return RuntimeRunnerAuthenticationService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        runtime_repository=cast(
            AgentRuntimeRepository,
            _FakeRuntimeRepository(runtime),
        ),
        verifier=RuntimeRunnerCredentialVerifier(Fernet.generate_key().decode()),
    )


@pytest.mark.asyncio
async def test_authenticate_requires_current_desired_generation() -> None:
    service = _service(_runtime(desired_generation=4))
    issued = service.verifier.issue(
        runtime_id="runtime-1",
        desired_generation=4,
    )

    credential = await service.authenticate_runner(issued.token)

    assert credential.runtime_id == "runtime-1"
    assert credential.desired_generation == 4
    assert credential.credential_id == issued.credential_id


@pytest.mark.asyncio
async def test_authenticate_rejects_absent_runtime() -> None:
    service = _service(None)
    issued = service.verifier.issue(
        runtime_id="runtime-1",
        desired_generation=4,
    )

    with pytest.raises(RuntimeRunnerCredentialInvalid):
        await service.authenticate_runner(issued.token)


@pytest.mark.asyncio
async def test_authenticate_rejects_stale_desired_generation() -> None:
    service = _service(_runtime(desired_generation=5))
    issued = service.verifier.issue(
        runtime_id="runtime-1",
        desired_generation=4,
    )

    with pytest.raises(RuntimeRunnerCredentialInvalid):
        await service.authenticate_runner(issued.token)


@pytest.mark.asyncio
async def test_authorize_rechecks_current_desired_generation() -> None:
    service = _service(_runtime(desired_generation=5))
    credential = service.verifier.verify(
        service.verifier.issue(
            runtime_id="runtime-1",
            desired_generation=5,
        ).token
    )

    assert await service.authorize_runner(credential)
    assert not await service.authorize_runner(
        dataclasses.replace(credential, desired_generation=4)
    )
