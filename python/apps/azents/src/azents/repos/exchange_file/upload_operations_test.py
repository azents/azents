"""PostgreSQL tests for exact Exchange browser upload publication and cleanup."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    WorkspaceUserRole,
)
from azents.core.exchange_upload import ExchangeUploadError, ExchangeUploadState
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.exchange_file import RDBExchangeFile
from azents.rdb.models.exchange_upload_operation import RDBExchangeUploadOperation
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFileCreate
from azents.repos.exchange_file.operations import (
    ExchangeFileCreateBatch,
    ExchangeFileOperationRepository,
    ExchangeFilePreviewCreate,
)
from azents.repos.exchange_file.upload_data import ExchangeUploadOperation
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 9, 29, tzinfo=datetime.UTC)
_DIGEST = "a" * 64
_EXPIRY = _NOW + datetime.timedelta(minutes=5)
_CLEANUP_AFTER = _EXPIRY + datetime.timedelta(minutes=5)


@dataclass(frozen=True)
class _Harness:
    repository: ExchangeFileOperationRepository
    session_manager: SessionManager[AsyncSession]
    workspace_id: str
    agent_id: str
    user_id: str
    other_user_id: str


async def _harness(
    session_manager: SessionManager[AsyncSession],
) -> _Harness:
    """Create a real Workspace membership and Agent without Runtime dependencies."""
    tag = uuid4().hex
    async with session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email=f"{tag}@example.com")
        )
        other = await UserRepository().create(
            session, UserCreate(email=f"other-{tag}@example.com")
        )
        await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Upload workspace", handle=f"upload-{tag}")
        )
        workspace_id = await WorkspaceRepository().resolve_id(session, f"upload-{tag}")
        assert workspace_id is not None
        for user_id in (user.id, other.id):
            await WorkspaceUserRepository().create(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    name="Uploader",
                    role=WorkspaceUserRole.MEMBER,
                ),
            )
        selection = make_test_model_selection_dict()
        agent = RDBAgent(
            workspace_id=workspace_id,
            name="Upload Agent",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection,
                lightweight_model_selection=selection,
            ),
            main_model_label="default",
            lightweight_model_label="lightweight",
        )
        session.add(agent)
        await session.flush()
        agent_id = agent.id
    return _Harness(
        repository=ExchangeFileOperationRepository(
            exchange_file_repository=ExchangeFileRepository(),
            agent_repository=AgentRepository(),
            agent_session_repository=AgentSessionRepository(),
            agent_run_repository=AgentRunRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            session_manager=session_manager,
        ),
        session_manager=session_manager,
        workspace_id=workspace_id,
        agent_id=agent_id,
        user_id=user.id,
        other_user_id=other.id,
    )


async def _prepare(harness: _Harness) -> ExchangeUploadOperation:
    """Reserve one exact operation before any external upload starts."""
    result = await harness.repository.prepare_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        filename="input.txt",
        media_type="text/plain",
        expected_size=3,
        expected_sha256=_DIGEST,
        now=_NOW,
        expires_at=_EXPIRY,
        cleanup_after=_CLEANUP_AFTER,
    )
    assert isinstance(result, Success)
    return result.value


def _batch(
    operation: ExchangeUploadOperation,
    *,
    preview: bool,
) -> ExchangeFileCreateBatch:
    """Build verified immutable metadata under reserved publication identities."""
    source = ExchangeFileCreate(
        id=operation.publication_id,
        workspace_id=operation.workspace_id,
        agent_id=operation.agent_id,
        filename=operation.filename,
        media_type=operation.media_type,
        size_bytes=operation.expected_size,
        sha256=operation.expected_sha256,
        origin_type=ExchangeFileOrigin.UPLOAD,
        provenance_kind=ExchangeFileProvenanceKind.HUMAN,
        created_by_user_id=operation.uploader_user_id,
        source_user_id=operation.uploader_user_id,
        retention_root_session_id=None,
        retention_bound_at=None,
        expires_at=_NOW + datetime.timedelta(days=30),
    )
    if not preview:
        return ExchangeFileCreateBatch(source=source, preview=None)
    return ExchangeFileCreateBatch(
        source=source,
        preview=ExchangeFilePreviewCreate(
            create=ExchangeFileCreate(
                id=operation.preview_file_id,
                workspace_id=operation.workspace_id,
                agent_id=operation.agent_id,
                filename="input.txt.preview.jpg",
                media_type="image/jpeg",
                size_bytes=1,
                sha256="b" * 64,
                origin_type=ExchangeFileOrigin.UPLOAD,
                provenance_kind=ExchangeFileProvenanceKind.PREVIEW,
                created_by_user_id=operation.uploader_user_id,
                source_exchange_file_id=operation.publication_id,
                retention_root_session_id=None,
                retention_bound_at=None,
                expires_at=source.expires_at,
            ),
            width=1,
            height=1,
            generated_at=_NOW,
        ),
    )


async def _claim(
    harness: _Harness,
    operation: ExchangeUploadOperation,
    *,
    claim_id: str,
    now: datetime.datetime,
) -> ExchangeUploadOperation:
    result = await harness.repository.claim_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id=claim_id,
        now=now,
        lease_until=now + datetime.timedelta(minutes=1),
    )
    assert isinstance(result, Success)
    return result.value


def test_operation_schema_preserves_cleanup_without_owner_foreign_keys() -> None:
    """Product deletion cannot cascade away persisted object cleanup identities."""
    table = RDBExchangeUploadOperation.__table__
    assert isinstance(table, sa.Table)
    assert not table.foreign_keys
    assert {index.name for index in table.indexes} == {
        "ix_exchange_upload_operations_due_cleanup"
    }
    cleanup_index = RDBExchangeUploadOperation.IX_DUE_CLEANUP
    assert cleanup_index.dialect_options["postgresql"]["where"] is None
    assert [column.name for column in cleanup_index.columns] == [
        "cleanup_after",
        "cleanup_lease_until",
        "id",
    ]
    state_type = table.c.state.type
    assert isinstance(state_type, ENUM)
    assert state_type.name == "exchange_upload_state"


async def test_prepare_binds_manifest_and_reserves_only_internal_ids(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    assert operation.workspace_id == harness.workspace_id
    assert operation.agent_id == harness.agent_id
    assert operation.uploader_user_id == harness.user_id
    assert operation.expected_size == 3 and operation.expected_sha256 == _DIGEST
    assert operation.state is ExchangeUploadState.PENDING
    assert operation.finalize_claim_id is None
    assert (
        len({operation.upload_id, operation.publication_id, operation.preview_file_id})
        == 3
    )
    async with rdb_session_manager() as session:
        row = await session.get(RDBExchangeUploadOperation, operation.upload_id)
        assert row is not None and row.publication_id == operation.publication_id
        assert await session.get(RDBExchangeFile, operation.publication_id) is None
    with pytest.raises(ValueError, match="SHA-256"):
        replace(operation, expected_sha256="A" * 64)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(operation, created_at=_NOW.replace(tzinfo=None))


async def test_claim_denies_other_uploader_and_revoked_current_membership(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    denied = await harness.repository.claim_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.other_user_id,
        upload_id=operation.upload_id,
        claim_id="other",
        now=_NOW,
        lease_until=_EXPIRY,
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == harness.workspace_id,
                RDBWorkspaceUser.user_id == harness.user_id,
            )
        )
    denied = await harness.repository.claim_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="revoked",
        now=_NOW,
        lease_until=_EXPIRY,
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)


async def test_prepare_authorizes_membership_and_rejects_invalid_manifest(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    invalid = await harness.repository.prepare_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        filename="input.txt",
        media_type="text/plain",
        expected_size=3,
        expected_sha256="A" * 64,
        now=_NOW,
        expires_at=_EXPIRY,
        cleanup_after=_CLEANUP_AFTER,
    )
    assert invalid == Failure(ExchangeUploadError.INVALID_REQUEST)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == harness.workspace_id,
                RDBWorkspaceUser.user_id == harness.user_id,
            )
        )
    denied = await harness.repository.prepare_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        filename="input.txt",
        media_type="text/plain",
        expected_size=3,
        expected_sha256=_DIGEST,
        now=_NOW,
        expires_at=_EXPIRY,
        cleanup_after=_CLEANUP_AFTER,
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)
    async with rdb_session_manager() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExchangeUploadOperation)
                .where(RDBExchangeUploadOperation.agent_id == harness.agent_id)
            )
            == 0
        )


async def test_agent_workspace_scope_cannot_change_after_prepare(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    async with rdb_session_manager() as session:
        handle = f"changed-{uuid4().hex}"
        await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Different scope", handle=handle)
        )
        new_workspace_id = await WorkspaceRepository().resolve_id(session, handle)
        assert new_workspace_id is not None
        await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=new_workspace_id,
                user_id=harness.user_id,
                name="Member in both scopes",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == harness.agent_id)
            .values(workspace_id=new_workspace_id)
        )
    denied = await harness.repository.claim_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        lease_until=_EXPIRY,
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)
    async with rdb_session_manager() as session:
        row = await session.get(RDBExchangeUploadOperation, operation.upload_id)
        assert row is not None and row.workspace_id == harness.workspace_id


async def test_claim_expiry_busy_and_replaced_token_fence_publication(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    claimed = await _claim(harness, operation, claim_id="first", now=_NOW)
    busy = await harness.repository.claim_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="second",
        now=_NOW,
        lease_until=_EXPIRY,
    )
    assert busy == Failure(ExchangeUploadError.BUSY)
    assert claimed.finalize_lease_until is not None
    elapsed = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="first",
        now=claimed.finalize_lease_until,
        batch=_batch(operation, preview=False),
    )
    assert elapsed == Failure(ExchangeUploadError.FENCED)
    replacement = await _claim(
        harness, operation, claim_id="second", now=claimed.finalize_lease_until
    )
    assert replacement.finalize_claim_id == "second"
    fenced = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="first",
        now=claimed.finalize_lease_until,
        batch=_batch(operation, preview=False),
    )
    assert fenced == Failure(ExchangeUploadError.FENCED)
    expired = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="second",
        now=_EXPIRY,
        batch=_batch(operation, preview=False),
    )
    assert expired == Failure(ExchangeUploadError.EXPIRED)
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None


@pytest.mark.parametrize(
    "changes",
    (
        {"id": "unreserved"},
        {"sha256": "c" * 64},
        {"size_bytes": 4},
        {"media_type": "application/octet-stream"},
        {"filename": "another.txt"},
        {"created_by_user_id": None},
        {"source_user_id": None},
        {"workspace_id": "other-workspace"},
        {"agent_id": "other-agent"},
    ),
)
async def test_finalize_rejects_mismatched_source_manifest(
    rdb_session_manager: SessionManager[AsyncSession],
    changes: dict[str, object],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    batch = _batch(operation, preview=False)
    mismatched = replace(batch, source=batch.source.model_copy(update=changes))
    result = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=mismatched,
    )
    assert result == Failure(ExchangeUploadError.MANIFEST_MISMATCH)
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None


async def test_finalize_reauthorizes_and_retries_same_exact_publication(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    batch = _batch(operation, preview=True)
    first = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=batch,
    )
    assert isinstance(first, Success)
    assert first.value.id == operation.publication_id
    assert first.value.preview_thumbnail_file_id == operation.preview_file_id
    replay = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="another-retry",
        now=_EXPIRY,
        batch=batch,
    )
    assert isinstance(replay, Success) and replay.value.id == first.value.id
    async with rdb_session_manager() as session:
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExchangeFile)
                .where(
                    RDBExchangeFile.id.in_(
                        [operation.publication_id, operation.preview_file_id]
                    )
                )
            )
            == 2
        )
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == harness.workspace_id,
                RDBWorkspaceUser.user_id == harness.user_id,
            )
        )
    denied = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="another-retry",
        now=_NOW,
        batch=batch,
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)


async def test_finalize_rejects_unreserved_preview_identity(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    batch = _batch(operation, preview=True)
    assert batch.preview is not None
    forged = replace(
        batch,
        preview=replace(
            batch.preview,
            create=batch.preview.create.model_copy(update={"id": uuid4().hex}),
        ),
    )
    denied = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=forged,
    )
    assert denied == Failure(ExchangeUploadError.MANIFEST_MISMATCH)
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None
        assert await session.get(RDBExchangeFile, operation.preview_file_id) is None


async def test_finalize_denies_revocation_between_claim_and_commit(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == harness.workspace_id,
                RDBWorkspaceUser.user_id == harness.user_id,
            )
        )
    denied = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=_batch(operation, preview=False),
    )
    assert denied == Failure(ExchangeUploadError.ACCESS_DENIED)
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None


async def test_authenticated_publication_load_never_recreates_a_missing_file(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    assert await harness.repository.load_agent_upload_publication(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        now=_NOW,
    ) == Failure(ExchangeUploadError.NOT_FOUND)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    finalized = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=_batch(operation, preview=False),
    )
    assert isinstance(finalized, Success)
    loaded = await harness.repository.load_agent_upload_publication(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        now=_EXPIRY,
    )
    assert isinstance(loaded, Success)
    assert loaded.value.id == finalized.value.id
    assert await harness.repository.load_agent_upload_publication(
        agent_id=harness.agent_id,
        user_id=harness.other_user_id,
        upload_id=operation.upload_id,
        now=_EXPIRY,
    ) == Failure(ExchangeUploadError.ACCESS_DENIED)
    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBExchangeFile).where(
                RDBExchangeFile.id == operation.publication_id
            )
        )
    assert await harness.repository.load_agent_upload_publication(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        now=_EXPIRY,
    ) == Failure(ExchangeUploadError.NOT_FOUND)
    retry = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_EXPIRY,
        batch=_batch(operation, preview=False),
    )
    assert retry == Failure(ExchangeUploadError.NOT_FOUND)


async def test_release_exact_live_claim_allows_retry_but_fences_old_token(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    now = datetime.datetime.now(datetime.UTC)
    prepared = await harness.repository.prepare_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        filename="input.txt",
        media_type="text/plain",
        expected_size=3,
        expected_sha256=_DIGEST,
        now=now,
        expires_at=now + datetime.timedelta(minutes=5),
        cleanup_after=now + datetime.timedelta(minutes=10),
    )
    assert isinstance(prepared, Success)
    operation = prepared.value
    await _claim(harness, operation, claim_id="first", now=now)
    assert not await harness.repository.release_agent_upload_claim(
        upload_id=operation.upload_id, claim_id="other-token"
    )
    assert await harness.repository.release_agent_upload_claim(
        upload_id=operation.upload_id, claim_id="first"
    )
    retry = await _claim(harness, operation, claim_id="retry", now=now)
    assert retry.finalize_claim_id == "retry"
    assert not await harness.repository.release_agent_upload_claim(
        upload_id=operation.upload_id, claim_id="first"
    )
    finalized = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="retry",
        now=now,
        batch=_batch(operation, preview=False),
    )
    assert isinstance(finalized, Success)
    assert not await harness.repository.release_agent_upload_claim(
        upload_id=operation.upload_id, claim_id="retry"
    )


async def test_cleanup_claim_fences_delayed_finalizer_even_with_stale_sampled_clock(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="finalize", now=_NOW)
    claimed = await harness.repository.claim_due_agent_upload_cleanup(
        now=_CLEANUP_AFTER,
        claim_id="cleanup",
        lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
        limit=1,
    )
    assert len(claimed) == 1
    result = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="finalize",
        now=_NOW,
        batch=_batch(operation, preview=False),
    )
    assert result == Failure(ExchangeUploadError.FENCED)
    assert await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="cleanup"
    )
    result = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="finalize",
        now=_NOW,
        batch=_batch(operation, preview=False),
    )
    assert result == Failure(ExchangeUploadError.FENCED)
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None


async def test_preview_failure_rolls_back_family_and_operation(
    rdb_session_manager: SessionManager[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)

    async def fail_preview(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("Preview metadata write failed")

    monkeypatch.setattr(
        harness.repository.exchange_file_repository,
        "set_preview_thumbnail_file_id",
        fail_preview,
    )
    with pytest.raises(RuntimeError, match="Preview metadata"):
        await harness.repository.finalize_agent_upload_operation(
            agent_id=harness.agent_id,
            user_id=harness.user_id,
            upload_id=operation.upload_id,
            claim_id="claim",
            now=_NOW,
            batch=_batch(operation, preview=True),
        )
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is None
        assert await session.get(RDBExchangeFile, operation.preview_file_id) is None
        row = await session.get(RDBExchangeUploadOperation, operation.upload_id)
        assert row is not None and row.state is ExchangeUploadState.PENDING


async def test_cleanup_is_due_bounded_and_survives_product_owner_deletion(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    assert (
        await harness.repository.claim_due_agent_upload_cleanup(
            now=_EXPIRY,
            claim_id="cleanup",
            lease_until=_CLEANUP_AFTER,
            limit=1,
        )
        == ()
    )
    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBAgent).where(RDBAgent.id == harness.agent_id)
        )
        await session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id == harness.workspace_id)
        )
        await session.execute(sa.delete(RDBUser).where(RDBUser.id == harness.user_id))
    claimed = await harness.repository.claim_due_agent_upload_cleanup(
        now=_CLEANUP_AFTER,
        claim_id="cleanup",
        lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
        limit=1,
    )
    assert len(claimed) == 1
    assert claimed[0].upload_id == operation.upload_id
    assert claimed[0].workspace_id == operation.workspace_id
    assert claimed[0].publication_id == operation.publication_id
    assert claimed[0].preview_file_id == operation.preview_file_id
    assert claimed[0].state is ExchangeUploadState.PENDING
    assert not await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="stale-cleanup"
    )
    assert await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="cleanup"
    )
    assert (
        await harness.repository.claim_due_agent_upload_cleanup(
            now=_CLEANUP_AFTER + datetime.timedelta(minutes=2),
            claim_id="next",
            lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=3),
            limit=1,
        )
        == ()
    )


async def test_finalized_cleanup_keeps_published_family_and_fences_old_cleanup_owner(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    await _claim(harness, operation, claim_id="claim", now=_NOW)
    result = await harness.repository.finalize_agent_upload_operation(
        agent_id=harness.agent_id,
        user_id=harness.user_id,
        upload_id=operation.upload_id,
        claim_id="claim",
        now=_NOW,
        batch=_batch(operation, preview=True),
    )
    assert isinstance(result, Success)
    claimed = await harness.repository.claim_due_agent_upload_cleanup(
        now=_CLEANUP_AFTER,
        claim_id="old-cleanup",
        lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
        limit=1,
    )
    assert claimed[0].state is ExchangeUploadState.FINALIZED
    assert (
        await harness.repository.claim_due_agent_upload_cleanup(
            now=_CLEANUP_AFTER,
            claim_id="busy-cleanup",
            lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
            limit=1,
        )
        == ()
    )
    reclaimed = await harness.repository.claim_due_agent_upload_cleanup(
        now=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
        claim_id="new-cleanup",
        lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=2),
        limit=1,
    )
    assert reclaimed[0].upload_id == operation.upload_id
    assert not await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="old-cleanup"
    )
    assert await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="new-cleanup"
    )
    async with rdb_session_manager() as session:
        assert await session.get(RDBExchangeFile, operation.publication_id) is not None
        assert await session.get(RDBExchangeFile, operation.preview_file_id) is not None


@pytest.mark.parametrize("finalized", [False, True])
async def test_completed_cleanup_reclaims_late_residue_after_one_hour(
    rdb_session_manager: SessionManager[AsyncSession], finalized: bool
) -> None:
    """Retained manifests authorize repeat cleanup, not renewed upload authority."""
    harness = await _harness(rdb_session_manager)
    operation = await _prepare(harness)
    if finalized:
        await _claim(harness, operation, claim_id="finalize", now=_NOW)
        result = await harness.repository.finalize_agent_upload_operation(
            agent_id=harness.agent_id,
            user_id=harness.user_id,
            upload_id=operation.upload_id,
            claim_id="finalize",
            now=_NOW,
            batch=_batch(operation, preview=True),
        )
        assert isinstance(result, Success)
    initial = await harness.repository.claim_due_agent_upload_cleanup(
        now=_CLEANUP_AFTER,
        claim_id="initial-cleanup",
        lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
        limit=1,
    )
    assert len(initial) == 1
    assert initial[0].upload_id == operation.upload_id
    before_finish = datetime.datetime.now(datetime.UTC)
    assert await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="initial-cleanup"
    )
    after_finish = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        row = await session.get(RDBExchangeUploadOperation, operation.upload_id)
        assert row is not None
        first_completed_at = row.cleanup_completed_at
        next_due = row.cleanup_after
        assert first_completed_at is not None
        assert before_finish <= first_completed_at <= after_finish
        assert next_due == first_completed_at + datetime.timedelta(hours=1)
        assert row.cleanup_claim_id is None
        assert row.cleanup_lease_until is None
    assert not await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="initial-cleanup"
    )
    for not_due in (after_finish, next_due - datetime.timedelta(microseconds=1)):
        assert (
            await harness.repository.claim_due_agent_upload_cleanup(
                now=not_due,
                claim_id="premature-cleanup",
                lease_until=not_due + datetime.timedelta(minutes=1),
                limit=1,
            )
            == ()
        )

    # Simulate the next physical sweep after a previously issued PUT completed late.
    repeated = await harness.repository.claim_due_agent_upload_cleanup(
        now=next_due,
        claim_id="late-residue-cleanup",
        lease_until=next_due + datetime.timedelta(minutes=1),
        limit=1,
    )
    assert len(repeated) == 1
    assert repeated[0].upload_id == operation.upload_id
    assert repeated[0].publication_id == operation.publication_id
    assert repeated[0].preview_file_id == operation.preview_file_id
    assert repeated[0].workspace_id == operation.workspace_id
    assert repeated[0].cleanup_completed_at == first_completed_at
    assert repeated[0].cleanup_claim_id == "late-residue-cleanup"
    assert repeated[0].state is (
        ExchangeUploadState.FINALIZED if finalized else ExchangeUploadState.PENDING
    )
    assert not await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="initial-cleanup"
    )
    before_second_finish = datetime.datetime.now(datetime.UTC)
    assert await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="late-residue-cleanup"
    )
    after_second_finish = datetime.datetime.now(datetime.UTC)
    assert not await harness.repository.finish_agent_upload_cleanup(
        upload_id=operation.upload_id, claim_id="late-residue-cleanup"
    )
    async with rdb_session_manager() as session:
        row = await session.get(RDBExchangeUploadOperation, operation.upload_id)
        assert row is not None and row.cleanup_completed_at is not None
        assert before_second_finish <= row.cleanup_completed_at <= after_second_finish
        assert row.cleanup_completed_at >= first_completed_at
        assert row.cleanup_after == row.cleanup_completed_at + datetime.timedelta(
            hours=1
        )
        assert row.cleanup_claim_id is None
        assert row.cleanup_lease_until is None
        for file_id in (operation.publication_id, operation.preview_file_id):
            file = await session.get(RDBExchangeFile, file_id)
            if finalized:
                assert file is not None
                assert file.blob_deleted_at is None
            else:
                assert file is None
    if not finalized:
        for now, error in (
            (_NOW, ExchangeUploadError.FENCED),
            (after_second_finish, ExchangeUploadError.EXPIRED),
        ):
            fenced = await harness.repository.claim_agent_upload_operation(
                agent_id=harness.agent_id,
                user_id=harness.user_id,
                upload_id=operation.upload_id,
                claim_id="late-finalize",
                now=now,
                lease_until=now + datetime.timedelta(minutes=1),
            )
            assert fenced == Failure(error)


async def test_recurring_cleanup_moves_finished_rows_behind_other_due_operations(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """The bounded oldest-deadline scan advances past each completed row."""
    harness = await _harness(rdb_session_manager)
    operations = [await _prepare(harness) for _ in range(3)]
    expected_ids = sorted(operation.upload_id for operation in operations)
    for position, expected_id in enumerate(expected_ids):
        claim_id = f"cleanup-{position}"
        claimed = await harness.repository.claim_due_agent_upload_cleanup(
            now=_CLEANUP_AFTER,
            claim_id=claim_id,
            lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
            limit=1,
        )
        assert len(claimed) == 1
        assert claimed[0].upload_id == expected_id
        assert await harness.repository.finish_agent_upload_cleanup(
            upload_id=expected_id, claim_id=claim_id
        )
    assert (
        await harness.repository.claim_due_agent_upload_cleanup(
            now=_CLEANUP_AFTER,
            claim_id="none-due",
            lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
            limit=1,
        )
        == ()
    )


async def test_concurrent_finalize_and_cleanup_claims_have_one_exact_winner(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Separate PostgreSQL connections prove locking, not an in-process guard."""

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    harness = await _harness(sessions)
    operation = await _prepare(harness)
    try:
        claims = await asyncio.gather(
            *(
                harness.repository.claim_agent_upload_operation(
                    agent_id=harness.agent_id,
                    user_id=harness.user_id,
                    upload_id=operation.upload_id,
                    claim_id=claim_id,
                    now=_NOW,
                    lease_until=_EXPIRY,
                )
                for claim_id in ("one", "two")
            )
        )
        winners = [result.value for result in claims if isinstance(result, Success)]
        assert len(winners) == 1
        assert len([r for r in claims if r == Failure(ExchangeUploadError.BUSY)]) == 1
        claim_id = winners[0].finalize_claim_id
        assert claim_id is not None
        results = await asyncio.gather(
            *(
                harness.repository.finalize_agent_upload_operation(
                    agent_id=harness.agent_id,
                    user_id=harness.user_id,
                    upload_id=operation.upload_id,
                    claim_id=claim_id,
                    now=_NOW,
                    batch=_batch(operation, preview=True),
                )
                for _ in range(2)
            )
        )
        for result in results:
            assert isinstance(result, Success)
            assert result.value.id == operation.publication_id
        cleanup_results = await asyncio.gather(
            *(
                harness.repository.claim_due_agent_upload_cleanup(
                    now=_CLEANUP_AFTER,
                    claim_id=claim,
                    lease_until=_CLEANUP_AFTER + datetime.timedelta(minutes=1),
                    limit=1,
                )
                for claim in ("cleanup-one", "cleanup-two")
            )
        )
        assert sum(len(result) for result in cleanup_results) == 1
    finally:
        async with sessions() as session:
            await session.execute(
                sa.delete(RDBExchangeFile).where(
                    RDBExchangeFile.workspace_id == harness.workspace_id,
                    RDBExchangeFile.id == operation.preview_file_id,
                )
            )
            await session.execute(
                sa.delete(RDBExchangeFile).where(
                    RDBExchangeFile.id == operation.publication_id
                )
            )
            await session.execute(
                sa.delete(RDBExchangeUploadOperation).where(
                    RDBExchangeUploadOperation.id == operation.upload_id
                )
            )
            await session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == harness.agent_id)
            )
            await session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == harness.workspace_id)
            )
            await session.execute(
                sa.delete(RDBUser).where(
                    RDBUser.id.in_([harness.user_id, harness.other_user_id])
                )
            )
