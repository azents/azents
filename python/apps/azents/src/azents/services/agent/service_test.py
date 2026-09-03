"""AgentService model snapshot behavior tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelectionInput,
    SelectableModelOption,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
    WorkspaceUserRole,
)
from azents.repos.agent.data import Agent
from azents.services.terminal_policy.invalidation import (
    NoopTerminalPolicyInvalidationPublisher,
    TerminalPolicySourceInvalidation,
    TerminalPolicySourceScope,
)
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.types import require_instance

from ..runtime_profile_workspace.service import RuntimeProfileWorkspaceUnavailable
from . import AgentService, _terminal_denied_scope
from .data import AgentCreateInput, ModelRequired, RuntimeProfileSelectionInvalid

_NOW = datetime.datetime.now(datetime.timezone.utc)


def test_terminal_denied_scope_reports_each_policy_owner() -> None:
    """Effective Terminal denial names the first authoritative scope."""
    assert (
        _terminal_denied_scope(
            capability=AgentRuntimeCapability.NONE,
            runtime_profile_available=False,
            runtime_profile_reason="runtime_profile_unconfigured",
            infrastructure_terminal_enabled=None,
            workspace_terminal_enabled=None,
            agent_terminal_enabled=True,
        )
        == "runtime"
    )
    assert (
        _terminal_denied_scope(
            capability=AgentRuntimeCapability.MANAGED,
            runtime_profile_available=True,
            runtime_profile_reason=None,
            infrastructure_terminal_enabled=False,
            workspace_terminal_enabled=True,
            agent_terminal_enabled=True,
        )
        == "provider_profile"
    )
    assert (
        _terminal_denied_scope(
            capability=AgentRuntimeCapability.MANAGED,
            runtime_profile_available=True,
            runtime_profile_reason=None,
            infrastructure_terminal_enabled=True,
            workspace_terminal_enabled=False,
            agent_terminal_enabled=True,
        )
        == "workspace_profile"
    )
    assert (
        _terminal_denied_scope(
            capability=AgentRuntimeCapability.MANAGED,
            runtime_profile_available=True,
            runtime_profile_reason=None,
            infrastructure_terminal_enabled=True,
            workspace_terminal_enabled=True,
            agent_terminal_enabled=False,
        )
        == "agent"
    )


def _make_agent(
    agent_id: str = "agent-1",
    *,
    runtime_profile_id: str | None = None,
    runtime_capability: AgentRuntimeCapability = AgentRuntimeCapability.NONE,
) -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection()
    return Agent(
        id=agent_id,
        workspace_id="ws-1",
        name="Test agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[
            SelectableModelOption(
                label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                model_selection=selection,
                settings=make_test_model_settings(),
            )
        ],
        main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        external_channel_default_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_profile_id=runtime_profile_id,
        runtime_profile_selection_version=1,
        runtime_capability=runtime_capability,
        runtime_capability_version=1,
        terminal_enabled=True,
        memory_enabled=True,
        tool_search_enabled=False,
        max_turns=None,
        auto_archive_ttl_days=30,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _avatar(key: str) -> StoredImage:
    """Create one internal avatar snapshot."""
    file = StoredImageFile(
        key=key,
        content_type="image/webp",
        size_bytes=1,
        width=512,
        height=512,
    )
    return StoredImage(
        filename="avatar.webp",
        default=file,
        thumbnails=StoredImageThumbnails(large=file),
        original=None,
        uploaded_at=_NOW,
    )


def _make_service() -> AgentService:
    """Create AgentService with mock dependencies."""
    repository = AsyncMock()
    admin_repository = AsyncMock()
    workspace_model_settings_repository = AsyncMock()
    model_catalog_read_service = AsyncMock()
    workspace_user_repository = AsyncMock()
    agent_decommission_repository = AsyncMock()
    archived_session_retention_repository = AsyncMock()
    runtime_profile_repository = AsyncMock()
    runtime_profile_service = AsyncMock()
    upload_service = AsyncMock()
    s3_service = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    return AgentService(
        repository=repository,
        admin_repository=admin_repository,
        workspace_model_settings_repository=workspace_model_settings_repository,
        model_catalog_read_service=model_catalog_read_service,
        workspace_user_repository=workspace_user_repository,
        agent_decommission_repository=agent_decommission_repository,
        archived_session_retention_repository=archived_session_retention_repository,
        runtime_profile_repository=runtime_profile_repository,
        runtime_profile_service=runtime_profile_service,
        upload_service=upload_service,
        s3_service=s3_service,
        workspace_s3_bucket="bucket",
        avatar_cdn_base_url=None,
        terminal_policy_invalidation_publisher=(
            NoopTerminalPolicyInvalidationPublisher()
        ),
        session_manager=session_manager,
    )


async def test_terminal_policy_invalidation_publishes_only_after_commit() -> None:
    """A committed Agent policy change invalidates after its DB transaction."""
    service = _make_service()
    repository = require_instance(service.repository, AsyncMock)
    existing = _make_agent()
    updated = existing.model_copy(update={"terminal_enabled": False})
    repository.get_by_id.return_value = existing
    repository.update_by_id.return_value = Success(updated)
    completed_transactions = 0
    invalidations: list[TerminalPolicySourceInvalidation] = []

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        nonlocal completed_transactions
        yield AsyncMock(spec=AsyncSession)
        completed_transactions += 1

    class _Publisher:
        async def publish_terminal_policy_invalidation(
            self,
            invalidation: TerminalPolicySourceInvalidation,
        ) -> None:
            assert completed_transactions == 2
            invalidations.append(invalidation)

    service.session_manager = session_manager
    service.terminal_policy_invalidation_publisher = _Publisher()

    result = await service.update_by_id(
        existing.id,
        {"terminal_enabled": False},
        workspace_id=existing.workspace_id,
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    assert invalidations == [
        TerminalPolicySourceInvalidation(
            scope=TerminalPolicySourceScope.AGENT,
            source_id=existing.id,
            source_version=updated.updated_at.isoformat(),
        )
    ]


async def test_terminal_policy_invalidation_is_not_published_on_rollback() -> None:
    """A failed Agent policy write never publishes volatile invalidation."""
    service = _make_service()
    repository = require_instance(service.repository, AsyncMock)
    existing = _make_agent()
    repository.get_by_id.return_value = existing
    repository.update_by_id.side_effect = RuntimeError("write failed")
    invalidations: list[TerminalPolicySourceInvalidation] = []

    class _Publisher:
        async def publish_terminal_policy_invalidation(
            self,
            invalidation: TerminalPolicySourceInvalidation,
        ) -> None:
            invalidations.append(invalidation)

    service.terminal_policy_invalidation_publisher = _Publisher()

    with pytest.raises(RuntimeError, match="write failed"):
        await service.update_by_id(
            existing.id,
            {"terminal_enabled": False},
            workspace_id=existing.workspace_id,
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.OWNER,
        )

    assert invalidations == []


class TestAgentServiceModelSelection:
    """Agent model selection copy behavior tests."""

    async def test_create_requires_model_when_workspace_default_absent(self) -> None:
        """Creation without model selection fails when workspace default is absent."""
        service = _make_service()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = require_instance(
            service.workspace_model_settings_repository, AsyncMock
        )
        settings_repo.get_or_create.return_value = settings

        result = await service.create(
            AgentCreateInput(workspace_id="ws-1", name="agent"),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ModelRequired)

    async def test_create_bootstraps_default_from_explicit_model(self) -> None:
        """Explicit model creation sets workspace default."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = require_instance(
            service.workspace_model_settings_repository, AsyncMock
        )
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        agent_repo = require_instance(service.repository, AsyncMock)
        admin_repo = require_instance(service.admin_repository, AsyncMock)
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        agent_repo.create.return_value = _make_agent()
        admin_repo.create.return_value = AsyncMock()

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        settings_repo.set_default_model_if_empty.assert_awaited_once()
        repository_create = agent_repo.create.await_args.args[1]
        assert repository_create.runtime_profile_id is None
        assert repository_create.runtime_capability is AgentRuntimeCapability.NONE
        assert repository_create.tool_search_enabled is True
        assert result.value.runtime_capability is AgentRuntimeCapability.NONE
        assert result.value.runtime_profile_configuration_status == "not_applicable"
        assert result.value.runtime_add_available is True
        assert result.value.runtime_remove_available is False
        runtime_profile_service = require_instance(
            service.runtime_profile_service, AsyncMock
        )
        runtime_profile_service.require_available_agent_profile.assert_not_awaited()
        runtime_profile_repository = require_instance(
            service.runtime_profile_repository, AsyncMock
        )
        runtime_profile_repository.enqueue_reconcile_task.assert_not_awaited()

    async def test_create_with_explicit_runtime_profile_is_managed(self) -> None:
        """Explicit available Runtime selection grants managed capability."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = require_instance(
            service.workspace_model_settings_repository, AsyncMock
        )
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        agent_repo = require_instance(service.repository, AsyncMock)
        admin_repo = require_instance(service.admin_repository, AsyncMock)
        runtime_profile_service = require_instance(
            service.runtime_profile_service, AsyncMock
        )
        runtime_profile_repository = require_instance(
            service.runtime_profile_repository, AsyncMock
        )
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        runtime_profile_service.get_profile.return_value = SimpleNamespace(
            available=True,
            reason_code=None,
            infrastructure_profile=SimpleNamespace(terminal_enabled=True),
            profile=SimpleNamespace(terminal_enabled=True),
        )
        agent_repo.create.return_value = _make_agent(
            runtime_profile_id="profile-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
        )
        admin_repo.create.return_value = AsyncMock()

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
                runtime_profile_id="profile-1",
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_session, repository_create = agent_repo.create.await_args.args
        profile_session = (
            runtime_profile_service.require_available_agent_profile.await_args.args[0]
        )
        assert profile_session is repository_session
        assert repository_create.runtime_profile_id == "profile-1"
        assert repository_create.runtime_capability is AgentRuntimeCapability.MANAGED
        assert result.value.runtime_capability is AgentRuntimeCapability.MANAGED
        assert result.value.runtime_profile_configuration_status == "configured"
        assert result.value.runtime_add_available is False
        assert result.value.runtime_remove_available is True
        assert result.value.effective_terminal_enabled is True
        assert result.value.terminal_denied_scope is None
        runtime_profile_repository.enqueue_reconcile_task.assert_awaited_once()

    async def test_create_rejects_unavailable_explicit_runtime_profile(self) -> None:
        """Unavailable explicit Runtime selection fails before Agent persistence."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = require_instance(
            service.workspace_model_settings_repository, AsyncMock
        )
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        agent_repo = require_instance(service.repository, AsyncMock)
        runtime_profile_service = require_instance(
            service.runtime_profile_service, AsyncMock
        )
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        runtime_profile_service.require_available_agent_profile.side_effect = (
            RuntimeProfileWorkspaceUnavailable(
                code="runtime_profile_unavailable",
                message="Runtime Profile is unavailable",
            )
        )

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
                runtime_profile_id="profile-1",
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RuntimeProfileSelectionInvalid)
        assert result.error.code == "runtime_profile_unavailable"
        agent_repo.create.assert_not_awaited()

    async def test_create_preserves_explicit_tool_search_opt_out(self) -> None:
        """Creation forwards an explicit Tool Search opt-out to the repository."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = require_instance(
            service.workspace_model_settings_repository, AsyncMock
        )
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        agent_repo = require_instance(service.repository, AsyncMock)
        admin_repo = require_instance(service.admin_repository, AsyncMock)
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        agent_repo.create.return_value = _make_agent()
        admin_repo.create.return_value = AsyncMock()

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
                tool_search_enabled=False,
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_create = agent_repo.create.await_args.args[1]
        assert repository_create.tool_search_enabled is False

    async def test_runtime_free_update_cannot_select_runtime_profile(self) -> None:
        """Runtime-free Agents require the dedicated add transition."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        repository.get_by_id.return_value = _make_agent()

        result = await service.update_by_id(
            "agent-1",
            {
                "runtime_profile_id": "profile-1",
                "expected_runtime_profile_selection_version": 1,
            },
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            role=WorkspaceUserRole.OWNER,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RuntimeProfileSelectionInvalid)
        assert result.error.code == "runtime_action_required"
        repository.replace_runtime_profile_selection.assert_not_awaited()

    async def test_runtime_profile_update_rechecks_capability_under_lock(self) -> None:
        """A concurrent removal fence blocks stale Runtime Profile updates."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        repository.get_by_id.return_value = _make_agent(
            runtime_profile_id="profile-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
        )
        repository.lock_by_id.return_value = _make_agent(
            runtime_capability=AgentRuntimeCapability.REMOVING,
        )

        result = await service.update_by_id(
            "agent-1",
            {
                "runtime_profile_id": "profile-2",
                "expected_runtime_profile_selection_version": 1,
            },
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            role=WorkspaceUserRole.OWNER,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RuntimeProfileSelectionInvalid)
        assert result.error.code == "runtime_removal_in_progress"
        repository.lock_by_id.assert_awaited_once()
        repository.replace_runtime_profile_selection.assert_not_awaited()
        repository.update_by_id.assert_not_awaited()

    async def test_runtime_profile_clear_replaces_runtime_authority_atomically(
        self,
    ) -> None:
        """Explicit null clears selection through the atomic Runtime transition."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        selected_agent = _make_agent(
            runtime_profile_id="profile-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
        )
        cleared_agent = selected_agent.model_copy(
            update={
                "runtime_profile_id": None,
                "runtime_profile_selection_version": 2,
            }
        )
        repository.get_by_id.return_value = selected_agent
        repository.lock_by_id.return_value = selected_agent
        repository.update_by_id.return_value = Success(cleared_agent)
        runtime_profile_repository = require_instance(
            service.runtime_profile_repository, AsyncMock
        )
        clear_selection = (
            runtime_profile_repository.clear_agent_runtime_profile_selection
        )
        clear_selection.return_value = True

        result = await service.update_by_id(
            "agent-1",
            {
                "runtime_profile_id": None,
                "expected_runtime_profile_selection_version": 1,
            },
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            role=WorkspaceUserRole.OWNER,
        )

        assert isinstance(result, Success)
        assert result.value.runtime_profile_id is None
        clear_selection.assert_awaited_once()
        clear_session = clear_selection.await_args.args[0]
        lock_session = repository.lock_by_id.await_args.args[0]
        assert clear_session is lock_session
        assert clear_selection.await_args.kwargs == {
            "agent_id": "agent-1",
            "expected_selection_version": 1,
        }
        repository.replace_runtime_profile_selection.assert_not_awaited()
        runtime_profile_repository.enqueue_reconcile_task.assert_not_awaited()


class TestAgentServiceAvatarMutation:
    """Agent avatar mutation ownership tests."""

    async def test_finalize_avatar_leaves_old_blob_deletion_to_durable_cleanup(
        self,
    ) -> None:
        """Finalization persists the replacement without direct blob deletion."""
        service = _make_service()
        service.avatar_cdn_base_url = "https://cdn.example.test"
        repository = require_instance(service.repository, AsyncMock)
        old_avatar = _avatar("public/avatar/agent-1/large/old.webp")
        new_avatar = _avatar("public/avatar/agent-1/large/new.webp")
        repository.get_by_id.return_value = _make_agent().model_copy(
            update={"avatar": old_avatar}
        )
        repository.update_avatar.return_value = Success(
            _make_agent().model_copy(update={"avatar": new_avatar})
        )
        upload_service = require_instance(service.upload_service, AsyncMock)
        upload_service.finalize.return_value = new_avatar

        result = await service.finalize_avatar(
            "agent-1",
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            role=WorkspaceUserRole.OWNER,
            upload_key="uploads/avatar-1",
            filename="avatar.webp",
        )

        assert isinstance(result, Success)
        repository.update_avatar.assert_awaited_once()
        s3_service = require_instance(service.s3_service, AsyncMock)
        s3_service.delete.assert_not_awaited()

    async def test_remove_avatar_leaves_old_blob_deletion_to_durable_cleanup(
        self,
    ) -> None:
        """Removal persists null avatar without direct blob deletion."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        repository.get_by_id.return_value = _make_agent().model_copy(
            update={"avatar": _avatar("public/avatar/agent-1/large/old.webp")}
        )
        repository.update_avatar.return_value = Success(_make_agent())

        result = await service.remove_avatar(
            "agent-1",
            workspace_id="ws-1",
            workspace_user_id="wu-1",
            role=WorkspaceUserRole.OWNER,
        )

        assert isinstance(result, Success)
        repository.update_avatar.assert_awaited_once()
        s3_service = require_instance(service.s3_service, AsyncMock)
        s3_service.delete.assert_not_awaited()
