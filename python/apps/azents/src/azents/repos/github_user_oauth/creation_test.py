"""Real PostgreSQL publication, one-use scope and rollback evidence."""

import asyncio
import dataclasses
import datetime
import json
from types import SimpleNamespace
from typing import NamedTuple, Never
from unittest.mock import AsyncMock, create_autospec

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import AgentLifecycleStatus
from azents.core.github_user_creation import (
    GitHubUserCreationAttempt,
    GitHubUserCreationFinalSettings,
    GitHubUserCreationSettings,
    GitHubUserCreationSubject,
)
from azents.core.github_user_oauth import (
    GitHubUserCandidate,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_oauth import (
    RDBGitHubUserConnection,
    RDBGitHubUserCreation,
)
from azents.rdb.models.toolkit import (
    RDBAgentToolkitNamespaceReservation,
    RDBToolkitConfig,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.github_user_oauth.creation import GitHubUserCreationRepository
from azents.repos.github_user_oauth.operations_test import _Harness, _harness
from azents.repos.github_user_oauth.payloads import SetupPayload
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig, ToolkitCreate
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository


class CreationHarness(NamedTuple):
    """Structured handles for real database creation lifecycle tests."""

    existing: _Harness
    subject: GitHubUserCreationSubject
    repository: GitHubUserCreationRepository
    desired: ToolkitCreate
    attempt: GitHubUserCreationAttempt


async def _creation(manager: SessionManager[WriteSession]) -> CreationHarness:
    h = await _harness(manager)
    subject = GitHubUserCreationSubject(
        h.requester.user_id,
        h.requester.session_id,
        h.requester.workspace_id,
        None,
    )
    repository = GitHubUserCreationRepository(
        h.repository,
        create_autospec(ToolkitNamespaceRepository, instance=True),
    )
    desired = ToolkitCreate(
        workspace_id=subject.workspace_id,
        owner_agent_id=None,
        toolkit_type="github",
        name="Confirmed creation",
        slug="confirmed",
        config={"github_auth_type": "github_app_user"},
        credentials=json.dumps({"type": "github_app_user", "client_secret": "secret"}),
        always_expose_tools=False,
    )
    result = await repository.start(
        subject,
        desired=desired,
        setup=SetupPayload(
            registration=h.registration,
            redirect_uri="https://test/cb",
            nonce="nonce",
            code_verifier="verifier",
        ),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    return CreationHarness(h, subject, repository, desired, result.attempt)


def _settings() -> GitHubUserCreationSettings:
    return GitHubUserCreationFinalSettings(
        name="Final reviewed creation",
        slug="confirmed",
        description=None,
        prompt=None,
        enabled=True,
        always_expose_tools=False,
        toolsets=["repos", "projects"],
        timeout=12.0,
        inject_runtime_environment=True,
        runtime_risk_acknowledged=True,
    ).prepare(canonical_name="GitHub")


async def _assert_unpublished(manager: SessionManager[WriteSession]) -> None:
    async with manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBToolkitConfig.id).where(
                    RDBToolkitConfig.slug == "confirmed"
                )
            )
            is None
        )
        assert (
            await session.read_session.scalar(sa.select(RDBGitHubUserConnection.id))
            is None
        )


async def test_only_confirmation_publishes_account_and_toolkit(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, subject, repo, _, attempt = await _creation(rdb_session_manager)
    await _assert_unpublished(rdb_session_manager)
    assert "secret" not in repr(attempt)
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    reviewed = await repo.stage(
        subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("candidate-token", 42, "account", None),
    )
    assert reviewed.candidate is not None
    await _assert_unpublished(rdb_session_manager)
    toolkit_id = await repo.confirm(
        subject,
        attempt_id=attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    async with rdb_session_manager() as session:
        toolkit = await session.read_session.get(RDBToolkitConfig, toolkit_id)
        assert toolkit is not None and toolkit.slug == "confirmed"
        assert toolkit.name == "Final reviewed creation"
        assert toolkit.config == {
            "github_auth_type": "github_app_user",
            "toolsets": ["repos", "projects"],
            "timeout": 12.0,
            "inject_runtime_environment": True,
        }
        connection = await session.read_session.scalar(
            sa.select(RDBGitHubUserConnection)
        )
        assert connection is not None and connection.toolkit_id == toolkit_id
        assert h.cipher.decrypt(connection.encrypted_access_token) == "candidate-token"
        assert await session.read_session.get(RDBGitHubUserCreation, attempt.id) is None
    with pytest.raises(GitHubUserOAuthError):
        await repo.confirm(
            subject,
            attempt_id=attempt.id,
            registration=h.registration,
            settings=_settings(),
        )


@pytest.mark.parametrize("field", ["user_id", "session_id", "agent_id"])
async def test_exact_initiating_scope_is_required(
    rdb_session_manager: SessionManager[WriteSession],
    field: str,
) -> None:
    _, subject, repo, _, attempt = await _creation(rdb_session_manager)
    wrong = dataclasses.replace(subject, **{field: "x" * 32})
    with pytest.raises(GitHubUserOAuthError):
        await repo.load(wrong, attempt.id)
    await _assert_unpublished(rdb_session_manager)
    assert (await repo.load(subject, attempt.id)).id == attempt.id


async def test_claim_replay_expiry_and_cancel_never_publish(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    _, subject, repo, _, attempt = await _creation(rdb_session_manager)
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    with pytest.raises(GitHubUserOAuthError) as error:
        await repo.claim(
            subject,
            attempt_id=attempt.id,
            nonce="nonce",
            redirect_uri=attempt.redirect_uri,
        )
    assert error.value.code is GitHubUserErrorCode.STALE
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBGitHubUserCreation).values(
                expires_at=datetime.datetime.now(datetime.UTC)
                - datetime.timedelta(seconds=1)
            )
        )
    with pytest.raises(GitHubUserOAuthError):
        await repo.load(subject, attempt.id)
    assert await repo.cancel(subject, attempt.id) == ()
    await _assert_unpublished(rdb_session_manager)


async def test_cancel_returns_exact_candidate_and_leaves_no_toolkit(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, subject, repo, _, attempt = await _creation(rdb_session_manager)
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    await repo.stage(
        subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("cancel-token", 42, "account", None),
    )
    revocations = await repo.cancel(subject, attempt.id)
    assert len(revocations) == 1 and revocations[0].access_token == "cancel-token"
    await _assert_unpublished(rdb_session_manager)


async def test_failed_exchange_discard_leaves_no_toolkit(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    _, subject, repo, _, attempt = await _creation(rdb_session_manager)
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    await repo.discard_claimed(attempt.id)
    await _assert_unpublished(rdb_session_manager)
    with pytest.raises(GitHubUserOAuthError):
        await repo.load(subject, attempt.id)


async def test_confirmation_failure_rolls_back_toolkit_and_preserves_review(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h, subject, repo, _, attempt = await _creation(rdb_session_manager)
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    await repo.stage(
        subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("rollback-token", 42, "account", None),
    )
    original = ToolkitRepository.create

    async def fail_after_insert(
        repository: ToolkitRepository, session: WriteSession, data: ToolkitCreate
    ) -> ToolkitConfig:
        await original(repository, session, data)
        raise RuntimeError("injected after Toolkit insert")

    monkeypatch.setattr(ToolkitRepository, "create", fail_after_insert)
    with pytest.raises(RuntimeError, match="after Toolkit insert"):
        await repo.confirm(
            subject,
            attempt_id=attempt.id,
            registration=h.registration,
            settings=_settings(),
        )
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(sa.select(RDBGitHubUserConnection.id))
            is None
        )
        assert (
            await session.read_session.get(RDBGitHubUserCreation, attempt.id)
            is not None
        )
        assert (
            await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBToolkitConfig)
                .where(RDBToolkitConfig.slug == "confirmed")
            )
            == 0
        )


@pytest.mark.parametrize("fail_namespace", [False, True])
async def test_agent_owned_publication_includes_namespace_atomically(
    rdb_session_manager: SessionManager[WriteSession],
    monkeypatch: pytest.MonkeyPatch,
    fail_namespace: bool,
) -> None:
    h, shared, repo, desired, initial = await _creation(rdb_session_manager)
    await repo.cancel(shared, initial.id)
    async with rdb_session_manager() as session:
        agent = RDBAgent(
            workspace_id=shared.workspace_id,
            name="Creation Agent",
            model_selection={},
            lightweight_model_selection={},
            selectable_model_options=[
                {
                    "label": "default",
                    "candidates": [
                        {
                            "model_selection": {},
                            "settings": {
                                "context_window_tokens": None,
                                "max_output_tokens": None,
                                "builtin_tools": [],
                            },
                        }
                    ],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                }
            ],
            main_model_label="default",
            lightweight_model_label="default",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        agent_id = agent.id
    agents = AsyncMock(spec=AgentRepository)
    agents.get_by_id.return_value = SimpleNamespace(
        workspace_id=shared.workspace_id, lifecycle_status=AgentLifecycleStatus.ACTIVE
    )
    subject = dataclasses.replace(shared, agent_id=agent_id)
    repo = dataclasses.replace(
        repo,
        namespaces=ToolkitNamespaceRepository(),
        operations=dataclasses.replace(h.repository, agent_repository=agents),
    )
    result = await repo.start(
        subject,
        desired=desired.model_copy(update={"owner_agent_id": agent_id}),
        setup=SetupPayload(
            registration=h.registration,
            redirect_uri="https://test/cb",
            nonce="nonce",
            code_verifier="verifier",
        ),
        expires_at=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=10),
    )
    await repo.claim(
        subject,
        attempt_id=result.attempt.id,
        nonce="nonce",
        redirect_uri=result.attempt.redirect_uri,
    )
    await repo.stage(
        subject,
        attempt_id=result.attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("agent-token", 42, "account", None),
    )
    await _assert_unpublished(rdb_session_manager)
    async with rdb_session_manager() as session:
        assert (
            await session.read_session.scalar(
                sa.select(RDBAgentToolkitNamespaceReservation)
            )
            is None
        )
    if fail_namespace:
        original_namespace = ToolkitNamespaceRepository.ensure_active

        async def fail_after_namespace(
            repository: ToolkitNamespaceRepository,
            session: WriteSession,
            *,
            agent_id: str,
            toolkit_id: str,
            base_slug: str,
        ) -> Never:
            await original_namespace(
                repository,
                session,
                agent_id=agent_id,
                toolkit_id=toolkit_id,
                base_slug=base_slug,
            )
            raise RuntimeError("injected after namespace allocation")

        monkeypatch.setattr(
            ToolkitNamespaceRepository, "ensure_active", fail_after_namespace
        )
        with pytest.raises(RuntimeError, match="after namespace allocation"):
            await repo.confirm(
                subject,
                attempt_id=result.attempt.id,
                registration=h.registration,
                settings=_settings(),
            )
        await _assert_unpublished(rdb_session_manager)
        assert (
            await repo.load_review(subject, result.attempt.id)
        ).candidate is not None
        async with rdb_session_manager() as session:
            assert (
                await session.read_session.scalar(
                    sa.select(RDBAgentToolkitNamespaceReservation)
                )
                is None
            )
        return
    toolkit_id = await repo.confirm(
        subject,
        attempt_id=result.attempt.id,
        registration=h.registration,
        settings=_settings(),
    )
    async with rdb_session_manager() as session:
        namespace = await session.read_session.scalar(
            sa.select(RDBAgentToolkitNamespaceReservation)
        )
        assert namespace is not None and namespace.toolkit_id == toolkit_id
        assert namespace.agent_id == agent_id


async def test_metadata_requires_exact_live_review_not_pending_or_exchanging(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h, subject, repo, _, attempt = await _creation(rdb_session_manager)
    with pytest.raises(GitHubUserOAuthError) as error:
        await repo.load_review(subject, attempt.id)
    assert error.value.code is GitHubUserErrorCode.STALE
    await repo.claim(
        subject, attempt_id=attempt.id, nonce="nonce", redirect_uri=attempt.redirect_uri
    )
    with pytest.raises(GitHubUserOAuthError):
        await repo.load_review(subject, attempt.id)
    await repo.stage(
        subject,
        attempt_id=attempt.id,
        registration=h.registration,
        candidate=GitHubUserCandidate("candidate-token", 42, "actual-account", None),
    )
    reviewed = await repo.load_review(subject, attempt.id)
    assert reviewed.candidate is not None
    await _assert_unpublished(rdb_session_manager)
    await repo.cancel(subject, attempt.id)
    with pytest.raises(GitHubUserOAuthError) as error:
        await repo.load_review(subject, attempt.id)
    assert error.value.code is GitHubUserErrorCode.NOT_FOUND


@pytest.mark.parametrize("confirm_wins", [True, False])
async def test_same_attempt_confirm_cancel_serialize_on_real_postgres_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
    confirm_wins: bool,
) -> None:
    """Use independent transactions and explicit barriers without scheduler sleeps."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    h, subject, repo, _, attempt = await _creation(manager)
    try:
        await repo.claim(
            subject,
            attempt_id=attempt.id,
            nonce="nonce",
            redirect_uri=attempt.redirect_uri,
        )
        await repo.stage(
            subject,
            attempt_id=attempt.id,
            registration=h.registration,
            candidate=GitHubUserCandidate(
                "candidate-token", 42, "actual-account", None
            ),
        )
        lock_taken = asyncio.Event()
        competitor_started = asyncio.Event()
        release = asyncio.Event()
        original_row = GitHubUserCreationRepository._row

        async def gated_row(
            repository: GitHubUserCreationRepository,
            session: WriteSession,
            current_subject: GitHubUserCreationSubject,
            attempt_id: str,
            *,
            live: bool,
        ) -> RDBGitHubUserCreation:
            if live == confirm_wins:
                row = await original_row(
                    repository, session, current_subject, attempt_id, live=live
                )
                lock_taken.set()
                await release.wait()
                return row
            competitor_started.set()
            return await original_row(
                repository, session, current_subject, attempt_id, live=live
            )

        monkeypatch.setattr(GitHubUserCreationRepository, "_row", gated_row)

        async def confirm() -> str:
            return await repo.confirm(
                subject,
                attempt_id=attempt.id,
                registration=h.registration,
                settings=_settings(),
            )

        async def cancel() -> None:
            await repo.cancel(subject, attempt.id)

        winner = asyncio.create_task(confirm() if confirm_wins else cancel())
        await lock_taken.wait()
        loser = asyncio.create_task(cancel() if confirm_wins else confirm())
        await competitor_started.wait()
        release.set()
        await winner
        with pytest.raises(GitHubUserOAuthError) as error:
            await loser
        assert error.value.code is GitHubUserErrorCode.NOT_FOUND
        async with manager() as session:
            assert (
                await session.read_session.get(RDBGitHubUserCreation, attempt.id)
                is None
            )
            count = await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBToolkitConfig)
                .where(
                    RDBToolkitConfig.workspace_id == subject.workspace_id,
                    RDBToolkitConfig.slug == "confirmed",
                )
            )
            assert count == (1 if confirm_wins else 0)
            connection_count = await session.read_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBGitHubUserConnection)
                .join(RDBToolkitConfig)
                .where(RDBToolkitConfig.workspace_id == subject.workspace_id)
            )
            assert connection_count == (1 if confirm_wins else 0)
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == subject.workspace_id)
            )
