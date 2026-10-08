"""Parent deletion preserves exact-owned active, candidate and cleanup state."""

import asyncio
import dataclasses
import datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.github_user_oauth import (
    GitHubUserAttemptStatus,
    GitHubUserCleanupStatus,
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserAttempt,
    RDBGitHubUserCleanup,
    RDBGitHubUserConnection,
)
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.github_user_oauth.parent_guards import (
    assert_agent_delete_allowed,
    assert_workspace_delete_allowed,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


@dataclasses.dataclass(frozen=True)
class _ParentRows:
    workspace_id: str
    agent_id: str
    other_agent_id: str
    owned_toolkit_id: str
    shared_toolkit_id: str
    other_owned_toolkit_id: str


async def _parents(manager: SessionManager[WriteSession]) -> _ParentRows:
    async with manager() as session:
        workspace = RDBWorkspace(
            name="Parent guard test", handle="parent-guard-" + uuid4().hex[:8]
        )
        session.write_session.add(workspace)
        await session.write_session.flush()
        selection = make_test_model_selection()
        agents = [
            RDBAgent(
                workspace_id=workspace.id,
                name=name,
                model_selection=selection.model_dump(mode="json"),
                lightweight_model_selection=selection.model_dump(mode="json"),
                selectable_model_options=make_test_selectable_model_option_dicts(
                    model_selection=selection.model_dump(mode="json"),
                    lightweight_model_selection=selection.model_dump(mode="json"),
                ),
                main_model_label="default",
                lightweight_model_label="default",
            )
            for name in ("Owning Agent", "Attached Agent")
        ]
        session.write_session.add_all(agents)
        await session.write_session.flush()
        owned, other = agents
        toolkits = [
            RDBToolkitConfig(
                workspace_id=workspace.id,
                owner_agent_id=owner,
                toolkit_type="github",
                slug="github",
                name="GitHub user connection",
                config={"github_auth_type": "github_app_user"},
            )
            for owner in (owned.id, None, other.id)
        ]
        session.write_session.add_all(toolkits)
        await session.write_session.flush()
        owned_toolkit, shared, other_toolkit = toolkits
        session.write_session.add(
            RDBAgentToolkit(
                agent_id=owned.id, toolkit_id=shared.id, toolkit_type="github"
            )
        )
        return _ParentRows(
            workspace.id,
            owned.id,
            other.id,
            owned_toolkit.id,
            shared.id,
            other_toolkit.id,
        )


async def _connection(manager: SessionManager[WriteSession], toolkit_id: str) -> str:
    async with manager() as session:
        row = RDBGitHubUserConnection(
            toolkit_id=toolkit_id,
            app_id="123",
            account_id=42,
            account_login="execution-user",
            account_avatar_url=None,
            encrypted_access_token="encrypted-test-token",
            encrypted_registration="encrypted-test-registration",
            status=GitHubUserConnectionStatus.CONNECTED,
            failure_reason=None,
        )
        session.write_session.add(row)
        await session.write_session.flush()
        return row.id


async def _attempt(
    manager: SessionManager[WriteSession],
    parents: _ParentRows,
    *,
    status: GitHubUserAttemptStatus,
    in_flight: bool,
    candidate: str | None,
    issued: str | None,
) -> str:
    async with manager() as session:
        row = RDBGitHubUserAttempt(
            toolkit_id=parents.owned_toolkit_id,
            user_id="u" * 32,
            session_id="s" * 32,
            workspace_id=parents.workspace_id,
            agent_id=parents.agent_id,
            encrypted_setup="encrypted-test-setup",
            encrypted_candidate=candidate,
            encrypted_issued_token=issued,
            exchange_in_flight=in_flight,
            captured_connection_id=None,
            status=status,
            expires_at=datetime.datetime.now(datetime.UTC),
        )
        session.write_session.add(row)
        await session.write_session.flush()
        return row.id


async def test_agent_owned_active_connection_blocks_deletion_without_erasing_state(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    parents = await _parents(rdb_session_manager)
    connection_id = await _connection(rdb_session_manager, parents.owned_toolkit_id)
    with pytest.raises(GitHubUserOAuthError) as caught:
        async with rdb_session_manager() as session:
            await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
    assert caught.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    assert "Disconnect" in str(caught.value)
    assert "complete token cleanup" in str(caught.value)
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBAgent, parents.agent_id) is not None
        assert (
            await session.read_session.get(RDBGitHubUserConnection, connection_id)
            is not None
        )


async def test_shared_attachment_and_another_agents_toolkit_do_not_block_agent(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    parents = await _parents(rdb_session_manager)
    shared_id = await _connection(rdb_session_manager, parents.shared_toolkit_id)
    other_id = await _connection(rdb_session_manager, parents.other_owned_toolkit_id)
    async with rdb_session_manager() as session:
        await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
        await session.write_session.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == parents.agent_id)
        )
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBAgent, parents.agent_id) is None
        assert await session.read_session.get(RDBGitHubUserConnection, shared_id)
        assert await session.read_session.get(RDBGitHubUserConnection, other_id)
        assert (
            await session.read_session.scalar(
                sa.select(RDBAgentToolkit.id).where(
                    RDBAgentToolkit.agent_id == parents.agent_id
                )
            )
            is None
        )


@pytest.mark.parametrize(
    ("status", "in_flight", "candidate", "issued"),
    [
        (GitHubUserAttemptStatus.PENDING, False, None, None),
        (GitHubUserAttemptStatus.EXCHANGING, True, None, None),
        (GitHubUserAttemptStatus.REVIEW, False, "encrypted-candidate", None),
        (GitHubUserAttemptStatus.CANCELLED, True, None, None),
        (GitHubUserAttemptStatus.CANCELLED, False, None, "encrypted-issued"),
        (GitHubUserAttemptStatus.COMPLETED, False, "encrypted-candidate", None),
    ],
)
async def test_incomplete_attempt_blocks_even_when_expired_or_cancelled(
    rdb_session_manager: SessionManager[WriteSession],
    status: GitHubUserAttemptStatus,
    in_flight: bool,
    candidate: str | None,
    issued: str | None,
) -> None:
    parents = await _parents(rdb_session_manager)
    attempt_id = await _attempt(
        rdb_session_manager,
        parents,
        status=status,
        in_flight=in_flight,
        candidate=candidate,
        issued=issued,
    )
    with pytest.raises(GitHubUserOAuthError):
        async with rdb_session_manager() as session:
            await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBGitHubUserAttempt, attempt_id)


async def test_retired_cleanup_blocks_until_confirmed_removal(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    parents = await _parents(rdb_session_manager)
    async with rdb_session_manager() as session:
        cleanup = RDBGitHubUserCleanup(
            toolkit_id=parents.owned_toolkit_id,
            encrypted_payload="encrypted-test-cleanup",
            reason="disconnect",
            status=GitHubUserCleanupStatus.FAILED,
            failure_reason="provider_unavailable",
        )
        session.write_session.add(cleanup)
        await session.write_session.flush()
        cleanup_id = cleanup.id
    with pytest.raises(GitHubUserOAuthError):
        async with rdb_session_manager() as session:
            await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBGitHubUserCleanup, cleanup_id)
        await session.write_session.execute(
            sa.delete(RDBGitHubUserCleanup).where(RDBGitHubUserCleanup.id == cleanup_id)
        )
        await assert_agent_delete_allowed(session, agent_id=parents.agent_id)


@pytest.mark.parametrize(
    "status", [GitHubUserAttemptStatus.CANCELLED, GitHubUserAttemptStatus.COMPLETED]
)
async def test_only_token_free_terminal_attempts_are_pruned(
    rdb_session_manager: SessionManager[WriteSession],
    status: GitHubUserAttemptStatus,
) -> None:
    parents = await _parents(rdb_session_manager)
    attempt_id = await _attempt(
        rdb_session_manager,
        parents,
        status=status,
        in_flight=False,
        candidate=None,
        issued=None,
    )
    async with rdb_session_manager() as session:
        await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBGitHubUserAttempt, attempt_id) is None


@pytest.mark.parametrize("ownership", ["shared", "agent"])
async def test_workspace_guard_covers_both_ownerships_only_in_exact_workspace(
    rdb_session_manager: SessionManager[WriteSession], ownership: str
) -> None:
    parents = await _parents(rdb_session_manager)
    toolkit = (
        parents.shared_toolkit_id if ownership == "shared" else parents.owned_toolkit_id
    )
    await _connection(rdb_session_manager, toolkit)
    async with rdb_session_manager() as session:
        await assert_workspace_delete_allowed(session, workspace_id="x" * 32)
    with pytest.raises(GitHubUserOAuthError) as caught:
        async with rdb_session_manager() as session:
            await assert_workspace_delete_allowed(
                session, workspace_id=parents.workspace_id
            )
    assert caught.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    assert "Workspace" in str(caught.value)


async def test_old_authentication_modes_without_user_state_remain_deletable(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    parents = await _parents(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.owner_agent_id == parents.agent_id)
            .values(config={"github_auth_type": "pat"})
        )
        await assert_agent_delete_allowed(session, agent_id=parents.agent_id)
        await assert_workspace_delete_allowed(
            session, workspace_id=parents.workspace_id
        )


async def test_parent_guard_observes_setup_published_under_toolkit_lock(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Publication and delete admission serialize only through owned Toolkit rows."""
    del latest_db_schema
    writes = create_read_write_session_manager(rdb_engine)
    parents = await _parents(writes)
    guard_started = asyncio.Event()
    guard_waiting = asyncio.Event()

    def observe_query(
        connection: sa.Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        many: bool,
    ) -> None:
        if (
            guard_started.is_set()
            and "toolkit_configs.owner_agent_id" in statement
            and "FOR UPDATE" in statement
        ):
            guard_waiting.set()

    async def request_delete() -> None:
        guard_started.set()
        async with writes() as deleting:
            await assert_agent_delete_allowed(deleting, agent_id=parents.agent_id)
            pytest.fail("Published pending setup must block parent delete admission")

    event.listen(rdb_engine.sync_engine, "before_cursor_execute", observe_query)
    try:
        async with asyncio.timeout(5):
            async with writes() as setup:
                await setup.write_session.scalar(
                    sa.select(RDBToolkitConfig.id)
                    .where(RDBToolkitConfig.id == parents.owned_toolkit_id)
                    .with_for_update()
                )
                setup.write_session.add(
                    RDBGitHubUserAttempt(
                        toolkit_id=parents.owned_toolkit_id,
                        user_id="u" * 32,
                        session_id="s" * 32,
                        workspace_id=parents.workspace_id,
                        agent_id=parents.agent_id,
                        encrypted_setup="encrypted-test-setup",
                        encrypted_candidate=None,
                        encrypted_issued_token=None,
                        exchange_in_flight=False,
                        captured_connection_id=None,
                        status=GitHubUserAttemptStatus.PENDING,
                        expires_at=datetime.datetime.now(datetime.UTC),
                    )
                )
                await setup.write_session.flush()
                deleting = asyncio.create_task(request_delete())
                await guard_waiting.wait()
                assert not deleting.done()
            with pytest.raises(GitHubUserOAuthError) as caught:
                await deleting
            assert caught.value.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    finally:
        event.remove(rdb_engine.sync_engine, "before_cursor_execute", observe_query)
        async with writes() as cleanup:
            toolkit_ids = (
                parents.owned_toolkit_id,
                parents.shared_toolkit_id,
                parents.other_owned_toolkit_id,
            )
            await cleanup.write_session.execute(
                sa.delete(RDBGitHubUserAttempt).where(
                    RDBGitHubUserAttempt.toolkit_id.in_(toolkit_ids)
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBAgent).where(
                    RDBAgent.id.in_((parents.agent_id, parents.other_agent_id))
                )
            )
            await cleanup.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == parents.workspace_id)
            )
