"""AgentService model snapshot behavior tests."""

import datetime
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from fastapi import Depends
from fastapi.dependencies.utils import get_dependant
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelectionInput,
    SelectableModelCandidate,
    SelectableModelCandidateInput,
    SelectableModelOption,
    SelectableModelOptionInput,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
    WorkspaceUserRole,
)
from azents.repos.agent.data import Agent
from azents.repos.agent_operations import (
    AgentOperationNotAdmin,
    AgentOperationRuntimeProfileInvalid,
    AgentOperationsRepository,
)
from azents.repos.llm_catalog import LiteLLMSourceSnapshotRepository
from azents.repos.llm_catalog.data import LiteLLMSourceSnapshot
from azents.services.model_metadata import ModelMetadataService
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
from azents.testing.model_metadata import make_test_model_metadata_service
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.types import require_instance

from . import AgentService, _terminal_denied_scope
from .data import (
    AgentCreateInput,
    ModelRequired,
    NotAdmin,
    RuntimeProfileSelectionInvalid,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


def test_agent_service_dependency_graph_is_valid() -> None:
    """FastAPI can construct the completed Agent repository dependency graph."""

    def endpoint(service: Annotated[AgentService, Depends()]) -> None:
        del service

    assert get_dependant(path="/", call=endpoint).dependencies


class _CountingMetadataRepository(LiteLLMSourceSnapshotRepository):
    """Supply one local source fixture and count reads."""

    def __init__(self, snapshot: LiteLLMSourceSnapshot) -> None:
        self.snapshot = snapshot
        self.capture_count = 0

    async def get_latest_authoritative(
        self, session: AsyncSession, *, source_key: str
    ) -> LiteLLMSourceSnapshot:
        del session
        assert source_key == "litellm_model_cost"
        self.capture_count += 1
        return self.snapshot


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
                candidates=[
                    SelectableModelCandidate(
                        model_selection=selection,
                        settings=make_test_model_settings(),
                    )
                ],
                subagent_enabled=True,
                subagent_guidance=None,
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


def _model_option_input() -> SelectableModelOptionInput:
    """Create one canonical selectable label input."""
    return SelectableModelOptionInput(
        label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        candidates=[
            SelectableModelCandidateInput(
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                )
            )
        ],
    )


def _make_service() -> AgentService:
    """Create AgentService with mock dependencies."""
    repository = AsyncMock(spec=AgentOperationsRepository)
    model_catalog_read_service = AsyncMock()
    image_generation_catalog_service = AsyncMock()
    image_generation_catalog_service.validate_option.return_value = []
    runtime_profile_service = AsyncMock()
    upload_service = AsyncMock()
    s3_service = AsyncMock()

    return AgentService(
        model_metadata_service=make_test_model_metadata_service(snapshot=None),
        repository=repository,
        model_catalog_read_service=model_catalog_read_service,
        image_generation_catalog_service=image_generation_catalog_service,
        runtime_profile_service=runtime_profile_service,
        upload_service=upload_service,
        s3_service=s3_service,
        workspace_s3_bucket="bucket",
        avatar_cdn_base_url=None,
        terminal_policy_invalidation_publisher=(
            NoopTerminalPolicyInvalidationPublisher()
        ),
    )


async def test_terminal_policy_invalidation_publishes_only_after_commit() -> None:
    """A committed Agent policy change invalidates after its DB transaction."""
    service = _make_service()
    repository = require_instance(service.repository, AsyncMock)
    existing = _make_agent()
    updated = existing.model_copy(update={"terminal_enabled": False})
    repository.get_by_id.return_value = existing
    operation_completed = False
    invalidations: list[TerminalPolicySourceInvalidation] = []

    async def update_agent(**kwargs: object) -> Success[Agent]:
        nonlocal operation_completed
        del kwargs
        operation_completed = True
        return Success(updated)

    repository.update_by_id.side_effect = update_agent

    class _Publisher:
        async def publish_terminal_policy_invalidation(
            self,
            invalidation: TerminalPolicySourceInvalidation,
        ) -> None:
            assert operation_completed
            invalidations.append(invalidation)

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


class TestAgentServiceSourceContext:
    """API context uses the same captured maximum and math as runtime."""

    async def test_agent_list_shares_one_source_capture_and_runtime_math(self) -> None:
        """Multiple Agents and paired budgets do not repeat a large source read."""
        service = _make_service()
        agents: list[Agent] = []
        for agent_id in ("agent-1", "agent-2"):
            agent = _make_agent(agent_id)
            option = agent.selectable_model_options[0]
            candidate = option.candidates[0]
            selection = candidate.model_selection
            capabilities = selection.normalized_capabilities
            context = capabilities.context_window.model_copy(
                update={"default_input_tokens": None, "max_input_tokens": None}
            )
            selection = selection.model_copy(
                update={
                    "normalized_capabilities": capabilities.model_copy(
                        update={"context_window": context}
                    )
                }
            )
            updated_option = option.model_copy(
                update={
                    "candidates": [
                        candidate.model_copy(update={"model_selection": selection})
                    ]
                }
            )
            agents.append(
                agent.model_copy(
                    update={
                        "model_selection": selection,
                        "lightweight_model_selection": selection,
                        "selectable_model_options": [updated_option],
                    }
                )
            )
        source_key = agents[0].model_selection.model_identifier
        snapshot = LiteLLMSourceSnapshot(
            id="source-id",
            source_key="litellm_model_cost",
            source_url=None,
            source_hash="source-hash",
            model_count=1,
            litellm_version=None,
            loaded_source="remote",
            payload={source_key: {"max_input_tokens": 256_000}},
            created_at=_NOW,
        )
        repository = _CountingMetadataRepository(snapshot)
        static_service = make_test_model_metadata_service(snapshot=snapshot)
        service.model_metadata_service = ModelMetadataService(
            session_manager=static_service.session_manager,
            source_snapshot_repository=repository,
        )
        agent_repository = require_instance(service.repository, AsyncMock)
        agent_repository.list_by_workspace.return_value = SimpleNamespace(items=agents)
        result = await service.list_by_workspace(
            "ws-1",
            workspace_user_id="owner",
            role=WorkspaceUserRole.OWNER,
        )
        assert repository.capture_count == 1
        assert len(result.items) == 2
        for item in result.items:
            assert item.effective_context_window_tokens == 256_000
            assert item.effective_auto_compaction_threshold_tokens == 230_400

    async def test_saved_maximum_avoids_source_capture(self) -> None:
        """A complete capability snapshot does not need fallback source metadata."""
        service = _make_service()
        agent = _make_agent()
        option = agent.selectable_model_options[0]
        candidate = option.candidates[0]
        selection = candidate.model_selection
        capabilities = selection.normalized_capabilities
        selection = selection.model_copy(
            update={
                "normalized_capabilities": capabilities.model_copy(
                    update={
                        "context_window": capabilities.context_window.model_copy(
                            update={"max_input_tokens": 128_000}
                        )
                    }
                )
            }
        )
        agent = agent.model_copy(
            update={
                "selectable_model_options": [
                    option.model_copy(
                        update={
                            "candidates": [
                                candidate.model_copy(
                                    update={"model_selection": selection}
                                )
                            ]
                        }
                    )
                ]
            }
        )
        snapshot = LiteLLMSourceSnapshot(
            id="source-id",
            source_key="litellm_model_cost",
            source_url=None,
            source_hash="source-hash",
            model_count=0,
            litellm_version=None,
            loaded_source="remote",
            payload={},
            created_at=_NOW,
        )
        repository = _CountingMetadataRepository(snapshot)
        static_service = make_test_model_metadata_service(snapshot=snapshot)
        service.model_metadata_service = ModelMetadataService(
            session_manager=static_service.session_manager,
            source_snapshot_repository=repository,
        )
        source = await service._capture_context_source([agent])
        assert source is None
        assert repository.capture_count == 0


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
        repository = require_instance(service.repository, AsyncMock)
        repository.get_workspace_model_settings.return_value = settings

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
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        repository = require_instance(service.repository, AsyncMock)
        repository.get_workspace_model_settings.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        repository.create.return_value = Success(_make_agent())

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                selectable_model_options=[_model_option_input()],
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_create = repository.create.await_args.args[0]
        assert repository_create.runtime_profile_id is None
        assert repository_create.runtime_capability is AgentRuntimeCapability.NONE
        assert repository_create.tool_search_enabled is True
        assert result.value.runtime_capability is AgentRuntimeCapability.NONE
        assert result.value.runtime_profile_configuration_status == "not_applicable"
        assert result.value.runtime_add_available is True
        assert result.value.runtime_remove_available is False

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
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        repository = require_instance(service.repository, AsyncMock)
        runtime_profile_service = require_instance(
            service.runtime_profile_service, AsyncMock
        )
        repository.get_workspace_model_settings.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        runtime_profile_service.get_profile.return_value = SimpleNamespace(
            available=True,
            reason_code=None,
            infrastructure_profile=SimpleNamespace(terminal_enabled=True),
            profile=SimpleNamespace(terminal_enabled=True),
        )
        repository.create.return_value = Success(
            _make_agent(
                runtime_profile_id="profile-1",
                runtime_capability=AgentRuntimeCapability.MANAGED,
            )
        )

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                selectable_model_options=[_model_option_input()],
                runtime_profile_id="profile-1",
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_create = repository.create.await_args.args[0]
        assert repository_create.runtime_profile_id == "profile-1"
        assert repository_create.runtime_capability is AgentRuntimeCapability.MANAGED
        assert result.value.runtime_capability is AgentRuntimeCapability.MANAGED
        assert result.value.runtime_profile_configuration_status == "configured"
        assert result.value.runtime_add_available is False
        assert result.value.runtime_remove_available is True
        assert result.value.effective_terminal_enabled is True
        assert result.value.terminal_denied_scope is None

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
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        repository = require_instance(service.repository, AsyncMock)
        repository.get_workspace_model_settings.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        repository.create.return_value = Failure(
            AgentOperationRuntimeProfileInvalid(
                code="runtime_profile_unavailable",
            )
        )

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                selectable_model_options=[_model_option_input()],
                runtime_profile_id="profile-1",
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, RuntimeProfileSelectionInvalid)
        assert result.error.code == "runtime_profile_unavailable"

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
        catalog_read_service = require_instance(
            service.model_catalog_read_service, AsyncMock
        )
        repository = require_instance(service.repository, AsyncMock)
        repository.get_workspace_model_settings.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        repository.create.return_value = Success(_make_agent())

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                selectable_model_options=[_model_option_input()],
                tool_search_enabled=False,
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_create = repository.create.await_args.args[0]
        assert repository_create.tool_search_enabled is False

    async def test_model_option_update_reconciles_stale_session_profiles(self) -> None:
        """Agent model changes replace active stale Session profile labels."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        existing = _make_agent()
        alternative_selection = make_test_model_selection(model_identifier="gpt-alt")
        alternative = SelectableModelOption(
            label="alternative",
            candidates=[
                SelectableModelCandidate(
                    model_selection=alternative_selection,
                    settings=make_test_model_settings(),
                )
            ],
            subagent_enabled=True,
            subagent_guidance=None,
        )
        existing = existing.model_copy(
            update={
                "selectable_model_options": [
                    *existing.selectable_model_options,
                    alternative,
                ]
            }
        )
        updated = existing.model_copy(
            update={
                "main_model_label": "alternative",
                "model_selection": alternative_selection,
            }
        )
        repository.get_by_id.return_value = existing
        repository.update_by_id.return_value = Success(updated)

        result = await service.update_by_id(
            existing.id,
            {"main_model_label": "alternative"},
            workspace_id=existing.workspace_id,
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.OWNER,
        )

        assert isinstance(result, Success)
        call = repository.update_by_id.await_args
        assert call.kwargs["agent_id"] == existing.id
        assert call.kwargs["valid_model_target_labels"] == ["default", "alternative"]
        assert call.kwargs["model_target_label"] == "alternative"
        assert call.kwargs["model_configuration_changed"]

    async def test_model_update_rejects_admin_revoked_during_resolution(self) -> None:
        """Final write rechecks authority after external model validation."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        catalog_read_service = require_instance(
            service.model_catalog_read_service,
            AsyncMock,
        )
        existing = _make_agent()
        selection = make_test_model_selection()
        steps: list[str] = []
        repository.get_by_id.return_value = existing
        repository.is_admin.return_value = True

        async def resolve_selection(**kwargs: object) -> Success[object]:
            del kwargs
            steps.append("model")
            return Success(selection)

        async def reject_write(**kwargs: object) -> Failure[AgentOperationNotAdmin]:
            del kwargs
            steps.append("write")
            return Failure(AgentOperationNotAdmin(agent_id=existing.id))

        catalog_read_service.resolve_agent_model_selection.side_effect = (
            resolve_selection
        )
        repository.update_by_id.side_effect = reject_write

        result = await service.update_by_id(
            existing.id,
            {"selectable_model_options": [_model_option_input()]},
            workspace_id=existing.workspace_id,
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MEMBER,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, NotAdmin)
        assert steps == ["model", "write"]

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
        repository.update_by_id.assert_not_awaited()

    async def test_runtime_profile_update_rechecks_capability_under_lock(self) -> None:
        """A concurrent removal fence blocks stale Runtime Profile updates."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        repository.get_by_id.return_value = _make_agent(
            runtime_profile_id="profile-1",
            runtime_capability=AgentRuntimeCapability.MANAGED,
        )
        repository.update_by_id.return_value = Failure(
            AgentOperationRuntimeProfileInvalid(code="runtime_removal_in_progress")
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
        repository.update_by_id.assert_awaited_once()

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
        repository.update_by_id.return_value = Success(cleared_agent)

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
        runtime_change = repository.update_by_id.await_args.kwargs[
            "runtime_profile_change"
        ]
        assert runtime_change.profile_id is None
        assert runtime_change.expected_version == 1


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

    async def test_finalize_avatar_rejects_admin_revoked_during_upload(self) -> None:
        """Final avatar write rechecks authority after upload finalization."""
        service = _make_service()
        repository = require_instance(service.repository, AsyncMock)
        upload_service = require_instance(service.upload_service, AsyncMock)
        existing = _make_agent()
        stored = _avatar("public/avatar/agent-1/large/new.webp")
        steps: list[str] = []
        repository.get_by_id.return_value = existing
        repository.is_admin.return_value = True

        async def finalize_upload(**kwargs: object) -> StoredImage:
            del kwargs
            steps.append("upload")
            return stored

        async def reject_write(**kwargs: object) -> Failure[AgentOperationNotAdmin]:
            del kwargs
            steps.append("write")
            return Failure(AgentOperationNotAdmin(agent_id=existing.id))

        upload_service.finalize.side_effect = finalize_upload
        repository.update_avatar.side_effect = reject_write

        result = await service.finalize_avatar(
            existing.id,
            workspace_id=existing.workspace_id,
            workspace_user_id="workspace-user-1",
            role=WorkspaceUserRole.MEMBER,
            upload_key="uploads/avatar-1",
            filename="avatar.webp",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, NotAdmin)
        assert steps == ["upload", "write"]

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
