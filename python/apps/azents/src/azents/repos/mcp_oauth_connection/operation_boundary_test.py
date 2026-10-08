"""Real PostgreSQL MCP OAuth stale refresh and failure settlement fences."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.core.enums import MCPOAuthConnectionStatus
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)
from azents.repos.model_candidate_health.operation_boundary_test import (
    _wait_for_candidate_blocker,
)


@pytest.mark.parametrize("failure", [False, True], ids=["refresh", "failure"])
async def test_held_replacement_credentials_fence_obsolete_mcp_finalization(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    failure: bool,
) -> None:
    """An old HTTP result waits for replacement then returns it without mutation."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    query = MCPOAuthConnectionRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    now = datetime.datetime.now(datetime.UTC)
    suffix = uuid4().hex
    async with writes() as setup:
        workspace = RDBWorkspace(
            name="MCP finalization boundary", handle=f"mcp-{suffix}"
        )
        setup.write_session.add(workspace)
        await setup.write_session.flush()
        toolkit = RDBToolkitConfig(
            workspace_id=workspace.id,
            owner_agent_id=None,
            toolkit_type="mcp",
            slug=f"mcp-{suffix}",
            name="MCP finalization boundary",
            config={},
        )
        setup.write_session.add(toolkit)
        await setup.write_session.flush()
        before = await query.upsert_connected(
            setup,
            toolkit_id=toolkit.id,
            issuer=None,
            resource=None,
            server_url="https://mcp.example.test",
            authorization_endpoint="https://auth.example.test/authorize",
            token_endpoint="https://auth.example.test/token",
            registration_endpoint=None,
            client_id="synthetic-client",
            client_secret="synthetic-secret",
            token_endpoint_auth_method="client_secret_post",
            scope=None,
            access_token="synthetic-original-access",
            refresh_token="synthetic-original-refresh",
            expires_at=now + datetime.timedelta(hours=1),
        )
        toolkit_id, workspace_id = toolkit.id, workspace.id

    finalizer_pids: asyncio.Queue[int] = asyncio.Queue()

    @asynccontextmanager
    async def observed_sessions() -> AsyncIterator[WriteSession]:
        async with writes() as session:
            pid = await session.read_session.scalar(sa.select(sa.func.pg_backend_pid()))
            assert isinstance(pid, int)
            await finalizer_pids.put(pid)
            yield session

    operation = MCPOAuthRuntimeOperationRepository(observed_sessions, query)
    task: asyncio.Task[None] | None = None
    try:
        async with writes() as replacing:
            replacement_pid = await replacing.read_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(replacement_pid, int)
            replacement = await query.update_tokens(
                replacing,
                toolkit_id=toolkit_id,
                access_token="synthetic-replacement-access",
                refresh_token="synthetic-replacement-refresh",
                expires_at=now + datetime.timedelta(hours=2),
            )
            assert replacement is not None
            assert replacement.id == before.id
            assert replacement.status is MCPOAuthConnectionStatus.CONNECTED

            async def finalize_obsolete() -> None:
                result = (
                    await operation.finalize_failure(
                        before=before,
                        toolkit_id=toolkit_id,
                        reconnect_required=True,
                    )
                    if failure
                    else await operation.finalize_refresh(
                        before=before,
                        toolkit_id=toolkit_id,
                        access_token="synthetic-obsolete-access",
                        refresh_token="synthetic-obsolete-refresh",
                        expires_at=now + datetime.timedelta(hours=3),
                    )
                )
                assert result == replacement

            task = asyncio.create_task(finalize_obsolete())
            finalizer_pid = await asyncio.wait_for(finalizer_pids.get(), timeout=5)
            assert finalizer_pid != replacement_pid
            await asyncio.wait_for(
                _wait_for_candidate_blocker(
                    rdb_engine,
                    blocked_pid=finalizer_pid,
                    blocker_pid=replacement_pid,
                ),
                timeout=5,
            )
            assert not task.done()
            await replacing.write_session.commit()
            await asyncio.wait_for(task, timeout=5)

        async with writes() as observer:
            retained = await query.get_by_toolkit_id(observer, toolkit_id)
            assert retained == replacement
            assert retained is not None
            assert retained.id == before.id
            assert retained.access_token == "synthetic-replacement-access"
            assert retained.refresh_token == "synthetic-replacement-refresh"
            assert retained.status is MCPOAuthConnectionStatus.CONNECTED
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with writes() as cleanup:
            await cleanup.write_session.execute(
                sa.delete(RDBToolkitConfig).where(RDBToolkitConfig.id == toolkit_id)
            )
            await cleanup.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
