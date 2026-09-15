"""Runtime Web durable Agent service repository tests."""

from typing import NamedTuple

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRuntimeCapability, LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthConfiguration,
    RuntimeWebActorKind,
)
from azents.repos.runtime_web.data import RuntimeWebOperationIdentity
from azents.repos.runtime_web.repository import (
    RuntimeWebRepository,
    RuntimeWebRepositoryConflict,
    RuntimeWebRepositoryQuotaExceeded,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


class _RuntimeWebAuthorityFixture(NamedTuple):
    """Field-named result for ``_authority_fixture``."""

    workspace_id: str
    agent_id: str
    user_id: str


async def _authority_fixture(
    session: AsyncSession,
    *,
    handle: str = "runtime-web",
    email: str = "runtime-web@example.com",
) -> _RuntimeWebAuthorityFixture:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Runtime Web", handle=handle),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="Runtime Web integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    model_selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="runtime-web-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Runtime Web agent",
        runtime_capability=AgentRuntimeCapability.MANAGED,
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.add(agent)
    await session.flush()
    user = await UserRepository().create(session, UserCreate(email=email))
    configuration = await session.get(RDBRuntimeWebAuthConfiguration, 1)
    assert configuration is not None
    configuration.enabled = True
    await session.flush()
    return _RuntimeWebAuthorityFixture(workspace_id, agent.id, user.id)


def _operation(
    key: str,
    *,
    actor_id: str,
    actor_kind: RuntimeWebActorKind = RuntimeWebActorKind.AGENT,
) -> RuntimeWebOperationIdentity:
    return RuntimeWebOperationIdentity(
        actor_kind=actor_kind,
        actor_id=actor_id,
        execution_id="runtime-web-test-run",
        operation_key=key,
    )


async def test_agent_request_creates_off_service_and_replays_exact_identity(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _authority_fixture(rdb_session)
    repository = RuntimeWebRepository(random_bytes=lambda size: b"a" * size)
    operation = _operation("request", actor_id=fixture.agent_id)

    created = await repository.request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=3000,
        label="Preview",
        operation=operation,
        service_limit=16,
    )
    replay = await repository.request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=3000,
        label="Preview",
        operation=operation,
        service_limit=16,
    )

    assert replay.service.id == created.service.id
    assert replay.service.hostname_key == created.service.hostname_key
    assert created.service.exposure_deadline_at is None
    assert created.service.selected_duration_seconds == 3_600
    assert len(created.service.hostname_key) == 12


async def test_user_transitions_preserve_selected_duration_contract(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _authority_fixture(
        rdb_session,
        handle="runtime-web-transitions",
        email="runtime-web-transitions@example.com",
    )
    repository = RuntimeWebRepository()
    created = await repository.create_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=8080,
        label=None,
        selected_duration_seconds=3_600,
        turn_on=True,
        operation=_operation(
            "create",
            actor_id=fixture.user_id,
            actor_kind=RuntimeWebActorKind.USER,
        ),
        service_limit=16,
        active_agent_limit=16,
    )
    original_deadline = created.service.exposure_deadline_at
    assert original_deadline is not None

    updated = await repository.update_service(
        rdb_session,
        service_id=created.service.id,
        expected_revision=created.service.revision,
        label_present=True,
        label="Application",
        selected_duration_seconds=21_600,
        operation=_operation(
            "update",
            actor_id=fixture.user_id,
            actor_kind=RuntimeWebActorKind.USER,
        ),
    )
    assert updated.service.exposure_deadline_at == original_deadline
    assert updated.service.selected_duration_seconds == 21_600

    reset = await repository.reset_expiration(
        rdb_session,
        service_id=updated.service.id,
        expected_revision=updated.service.revision,
        operation=_operation(
            "reset",
            actor_id=fixture.user_id,
            actor_kind=RuntimeWebActorKind.USER,
        ),
    )
    assert reset.service.exposure_deadline_at is not None
    assert reset.service.exposure_deadline_at > original_deadline

    closed = await repository.close_service(
        rdb_session,
        service_id=reset.service.id,
        operation=_operation("close", actor_id=fixture.agent_id),
    )
    repeated = await repository.close_service(
        rdb_session,
        service_id=reset.service.id,
        operation=_operation("close-again", actor_id=fixture.agent_id),
    )
    assert closed.service.exposure_deadline_at is None
    assert repeated.service.exposure_deadline_at is None
    assert repeated.service.revision == closed.service.revision


async def test_stale_revision_and_quota_fail_without_partial_mutation(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _authority_fixture(
        rdb_session,
        handle="runtime-web-conflicts",
        email="runtime-web-conflicts@example.com",
    )
    repository = RuntimeWebRepository()
    created = await repository.request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=3000,
        label=None,
        operation=_operation("first", actor_id=fixture.agent_id),
        service_limit=1,
    )

    with pytest.raises(RuntimeWebRepositoryConflict, match="revision"):
        await repository.update_service(
            rdb_session,
            service_id=created.service.id,
            expected_revision=created.service.revision + 1,
            label_present=True,
            label="stale",
            selected_duration_seconds=None,
            operation=_operation(
                "stale",
                actor_id=fixture.user_id,
                actor_kind=RuntimeWebActorKind.USER,
            ),
        )

    with pytest.raises(RuntimeWebRepositoryQuotaExceeded) as error:
        await repository.request_service(
            rdb_session,
            workspace_id=fixture.workspace_id,
            agent_id=fixture.agent_id,
            port=3001,
            label=None,
            operation=_operation("second", actor_id=fixture.agent_id),
            service_limit=1,
        )
    assert error.value.scope == "agent_services"
    current = await repository.get_service_by_id(rdb_session, created.service.id)
    assert current is not None
    assert current.label is None


async def test_delete_and_recreate_never_reuses_service_identity(
    rdb_session: AsyncSession,
) -> None:
    fixture = await _authority_fixture(
        rdb_session,
        handle="runtime-web-recreate",
        email="runtime-web-recreate@example.com",
    )
    random_values = iter((b"a" * 8, b"b" * 8))
    repository = RuntimeWebRepository(random_bytes=lambda _size: next(random_values))
    created = await repository.request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=3000,
        label=None,
        operation=_operation("request-one", actor_id=fixture.agent_id),
        service_limit=16,
    )
    assert await repository.delete_service(
        rdb_session,
        agent_id=fixture.agent_id,
        service_id=created.service.id,
        expected_revision=created.service.revision,
        operation=_operation(
            "delete",
            actor_id=fixture.user_id,
            actor_kind=RuntimeWebActorKind.USER,
        ),
    )
    recreated = await repository.request_service(
        rdb_session,
        workspace_id=fixture.workspace_id,
        agent_id=fixture.agent_id,
        port=3000,
        label=None,
        operation=_operation("request-two", actor_id=fixture.agent_id),
        service_limit=16,
    )
    assert recreated.service.id != created.service.id
    assert recreated.service.hostname_key != created.service.hostname_key
