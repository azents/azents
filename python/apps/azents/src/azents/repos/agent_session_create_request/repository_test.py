"""AgentSession create-request repository tests."""

import dataclasses
import datetime
import importlib.util
import itertools
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import psycopg
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.schema import SchemaItem

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session_create_request import (
    RDBAgentSessionCreateRequest,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from .data import AgentSessionCreateRequestClaim
from .repository import AgentSessionCreateRequestRepository


def _load_create_request_migration() -> ModuleType:
    """Load the new-table migration without requiring an Alembic environment."""
    migration_path = (
        Path(__file__).resolve().parents[4]
        / "db-schemas"
        / "rdb"
        / "migrations"
        / "versions"
        / "076e7b6ec5e2_add_agent_session_create_requests.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_agent_session_create_request_migration",
        migration_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load AgentSession create-request migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_accepted_session_identity_is_a_retained_tombstone() -> None:
    """Session deletion preserves authority while User deletion releases it."""
    table = RDBAgentSessionCreateRequest.__table__

    assert table.c.agent_session_id.foreign_keys == set()
    assert {foreign_key.ondelete for foreign_key in table.c.user_id.foreign_keys} == {
        "CASCADE"
    }


def test_pending_snapshot_none_binds_as_sql_null() -> None:
    """Python None must satisfy the pending row's SQL-NULL invariant."""
    snapshot_type = RDBAgentSessionCreateRequest.__table__.c.input_buffer_snapshot.type

    assert isinstance(snapshot_type, postgresql.JSONB)
    assert snapshot_type.none_as_null is True
    bind_processor = snapshot_type.bind_processor(psycopg.dialect())
    assert bind_processor is not None
    assert bind_processor(None) is None


def test_completion_constraint_accepts_only_pending_or_complete_states() -> None:
    """The actual check SQL rejects every partially populated authority state."""
    field_names = (
        "agent_session_id",
        "input_buffer_id",
        "input_buffer_snapshot",
        "completed_at",
    )
    projected_fields = ", ".join(
        f":{field_name} AS {field_name}" for field_name in field_names
    )
    statement = sa.text(
        "SELECT CASE WHEN "
        f"{RDBAgentSessionCreateRequest.CK_COMPLETION.sqltext} "
        "THEN 1 ELSE 0 END "
        f"FROM (SELECT {projected_fields}) AS request_state"
    )

    with sa.create_engine("sqlite+pysqlite:///:memory:").connect() as connection:
        for presence in itertools.product((False, True), repeat=len(field_names)):
            values = {
                field_name: 1 if is_present else None
                for field_name, is_present in zip(
                    field_names,
                    presence,
                    strict=True,
                )
            }
            accepted = connection.scalar(statement, values)
            expected = all(presence) or not any(presence)

            assert accepted == int(expected), (presence, values)


def test_migration_matches_model_completion_invariant() -> None:
    """Migration and ORM agree on SQL NULL binding and completion check SQL."""
    migration = _load_create_request_migration()
    created_tables: dict[str, tuple[SchemaItem, ...]] = {}

    def capture_table(name: str, *items: SchemaItem) -> None:
        created_tables[name] = items

    migration.__dict__["op"] = SimpleNamespace(
        execute=lambda *_args, **_kwargs: None,
        create_table=capture_table,
        create_index=lambda *_args, **_kwargs: None,
    )
    migration.upgrade()

    table_items = created_tables["agent_session_create_requests"]
    snapshot_column = next(
        item
        for item in table_items
        if isinstance(item, sa.Column) and item.name == "input_buffer_snapshot"
    )
    completion_check = next(
        item
        for item in table_items
        if isinstance(item, sa.CheckConstraint)
        and item.name == RDBAgentSessionCreateRequest.CK_COMPLETION.name
    )

    assert isinstance(snapshot_column.type, postgresql.JSONB)
    assert snapshot_column.type.none_as_null is True
    assert str(completion_check.sqltext) == str(
        RDBAgentSessionCreateRequest.CK_COMPLETION.sqltext
    )


@dataclasses.dataclass(frozen=True)
class _CreateRequestScope:
    """Identifiers created for one repository test scope."""

    user_id: str
    agent_id: str
    agent_session_id: str


async def _create_scope(session: AsyncSession) -> _CreateRequestScope:
    """Create a User, Agent, and AgentSession for repository tests."""
    workspace_repository = WorkspaceRepository()
    workspace = await workspace_repository.create(
        session,
        WorkspaceCreate(
            name="Create request test",
            handle="create-request-repository-test",
        ),
    )
    assert isinstance(workspace, Success)
    workspace_id = await workspace_repository.resolve_id(
        session,
        "create-request-repository-test",
    )
    assert workspace_id is not None
    user = await UserRepository().create(
        session,
        UserCreate(email="create-request-repository@example.com"),
    )
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="Create request test integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Create request test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="create-request-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="create-request-model",
        ),
    )
    session.add(agent)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    return _CreateRequestScope(
        user_id=user.id,
        agent_id=agent.id,
        agent_session_id=agent_session.id,
    )


class TestAgentSessionCreateRequestRepository:
    """AgentSession create-request repository behavior."""

    async def test_claim_complete_and_retry_reuses_authority(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A completed unique claim is returned to later transactions."""
        scope = await _create_scope(rdb_session)
        repository = AgentSessionCreateRequestRepository()
        claim = AgentSessionCreateRequestClaim(
            user_id=scope.user_id,
            agent_id=scope.agent_id,
            client_request_id="create-request-1",
            payload_hash="a" * 64,
        )

        first = await repository.claim(rdb_session, claim)
        assert first.claimed is True
        completed = await repository.complete(
            rdb_session,
            request_id=first.record.id,
            agent_session_id=scope.agent_session_id,
            input_buffer_id="0123456789abcdef0123456789abcdef",
            input_buffer_snapshot={"id": "0123456789abcdef0123456789abcdef"},
            completed_at=datetime.datetime.now(datetime.UTC),
        )
        retry = await repository.claim(rdb_session, claim)

        assert retry.claimed is False
        assert retry.record == completed
        assert retry.record.agent_session_id == scope.agent_session_id
        assert retry.record.input_buffer_id == "0123456789abcdef0123456789abcdef"

    async def test_abandon_pending_claim_does_not_delete_completed_authority(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only an exact still-incomplete claim can be abandoned."""
        scope = await _create_scope(rdb_session)
        repository = AgentSessionCreateRequestRepository()
        claim = AgentSessionCreateRequestClaim(
            user_id=scope.user_id,
            agent_id=scope.agent_id,
            client_request_id="create-request-abandon",
            payload_hash="b" * 64,
        )
        pending = await repository.claim(rdb_session, claim)

        await repository.abandon_pending_claim(
            rdb_session,
            request_id=pending.record.id,
        )
        assert (
            await repository.get_by_key(
                rdb_session,
                user_id=scope.user_id,
                agent_id=scope.agent_id,
                client_request_id=claim.client_request_id,
            )
            is None
        )

        replacement = await repository.claim(rdb_session, claim)
        completed = await repository.complete(
            rdb_session,
            request_id=replacement.record.id,
            agent_session_id=scope.agent_session_id,
            input_buffer_id="1123456789abcdef0123456789abcdef",
            input_buffer_snapshot={"id": "1123456789abcdef0123456789abcdef"},
            completed_at=datetime.datetime.now(datetime.UTC),
        )
        with pytest.raises(
            RuntimeError,
            match="pending claim was not released",
        ):
            await repository.abandon_pending_claim(
                rdb_session,
                request_id=completed.id,
            )
        assert (
            await repository.get_by_key(
                rdb_session,
                user_id=scope.user_id,
                agent_id=scope.agent_id,
                client_request_id=claim.client_request_id,
            )
            == completed
        )
