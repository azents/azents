"""Deletion between external work and publication cannot attach new owned state."""

import dataclasses

import pytest
import sqlalchemy as sa

from azents.core.agent_mutation import AgentMutationReadOnly
from azents.core.toolkit_ownership import ToolkitOwnerKind
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.models.exchange_upload_operation import RDBExchangeUploadOperation
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.google_oauth import RDBGoogleConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_runtime_removal.repository_test import _create_agent
from azents.repos.exchange_file.upload_operations_test import (
    _NOW,
    _batch,
    _claim,
    _prepare,
)
from azents.repos.exchange_file.upload_operations_test import (
    _harness as upload_harness,
)
from azents.repos.github_user_oauth.operations_test import (
    _harness as github_harness,
)
from azents.repos.github_user_oauth.operations_test import (
    _review as github_review,
)
from azents.repos.google_oauth.management_test import (
    Harness as GoogleHarness,
)
from azents.repos.google_oauth.management_test import (
    _google,
    _settings,
)
from azents.repos.google_oauth.management_test import (
    _review as google_review,
)


@pytest.mark.parametrize("preview", [False, True])
async def test_upload_final_publication_rechecks_deletion_after_claim(
    rdb_session_manager: SessionManager[WriteSession], preview: bool
) -> None:
    h = await upload_harness(rdb_session_manager)
    operation = await _prepare(h)
    await _claim(h, operation, claim_id="verified-upload", now=_NOW)
    async with rdb_session_manager() as session:
        await AgentRepository().mark_decommissioning(session, h.agent_id)
    with pytest.raises(AgentMutationReadOnly):
        await h.repository.finalize_agent_upload_operation(
            agent_id=h.agent_id,
            user_id=h.user_id,
            upload_id=operation.upload_id,
            claim_id="verified-upload",
            now=_NOW,
            batch=_batch(operation, preview=preview),
        )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.get(RDBExchangeFile, operation.publication_id)
            is None
        )
        assert (
            await session.read_session.get(RDBExchangeFile, operation.preview_file_id)
            is None
        )
        # Native upload cleanup identity survives denial; it is not falsely published.
        row = await session.read_session.get(
            RDBExchangeUploadOperation, operation.upload_id
        )
        assert row is not None and row.finalized_at is None


async def test_github_reviewed_token_cannot_attach_after_deletion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await github_harness(rdb_session_manager)
    async with rdb_session_manager() as session:
        fixture = await _create_agent(session)
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fixture.agent_id)
            .values(workspace_id=h.requester.workspace_id)
        )
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.requester.toolkit_id)
            .values(owner_kind=ToolkitOwnerKind.AGENT, owner_agent_id=fixture.agent_id)
        )
    h = dataclasses.replace(
        h,
        repository=dataclasses.replace(
            h.repository, agent_repository=AgentRepository()
        ),
        requester=dataclasses.replace(h.requester, agent_id=fixture.agent_id),
    )
    attempt = await github_review(h, "reviewed-test-token")
    async with rdb_session_manager() as session:
        await AgentRepository().mark_decommissioning(session, fixture.agent_id)
    with pytest.raises(AgentMutationReadOnly):
        await h.repository.confirm(
            requester=h.requester, attempt_id=attempt.id, registration=h.registration
        )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserConnection.id).where(
                    RDBGitHubUserConnection.toolkit_id == h.requester.toolkit_id
                )
            )
            is None
        )


async def test_google_reviewed_candidate_cannot_attach_after_deletion(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _google(rdb_session_manager)
    async with rdb_session_manager() as session:
        fixture = await _create_agent(session)
        await session.write_session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == fixture.agent_id)
            .values(workspace_id=h.subject.workspace_id)
        )
    h = GoogleHarness(
        dataclasses.replace(h.repo, agents=AgentRepository()),
        dataclasses.replace(h.subject, agent_id=fixture.agent_id),
        h.registration,
        h.setup,
    )
    attempt = await google_review(h, None)
    async with rdb_session_manager() as session:
        await AgentRepository().mark_decommissioning(session, fixture.agent_id)
    with pytest.raises(AgentMutationReadOnly):
        await h.repo.confirm(
            h.subject,
            attempt_id=attempt.id,
            registration=h.registration,
            settings=_settings(),
        )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBToolkitConfig.id).where(
                    RDBToolkitConfig.owner_agent_id == fixture.agent_id
                )
            )
            is None
        )
        assert (
            await session.read_session.scalar(sa.select(RDBGoogleConnection.id)) is None
        )
