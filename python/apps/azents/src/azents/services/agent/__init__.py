"""Agent service."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    AgentModelSelectionInput,
    ModelParameters,
    SelectableModelOptionInput,
)
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import AgentType, WorkspaceUserRole
from azents.core.llm_mapping import to_runtime_model
from azents.core.s3.deps import get_s3_service
from azents.engine.context.window import (
    EffectiveContextWindow,
    compute_effective_context_window_tokens,
    get_max_input_tokens,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent, AgentCreate, AgentUpdate, NotFound
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_admin.data import AgentAdminCreate
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.llm_catalog import ModelCatalogReadService
from azents.services.model_options import (
    NormalizedSelectableModelOptions,
    build_legacy_selectable_model_options,
    normalize_selectable_model_options,
    normalize_stored_selectable_model_options,
)
from azents.services.uploads import UploadService, UploadValidationError
from azents.services.uploads.deps import get_upload_service
from azents.services.uploads.handlers.avatar import AvatarUploadHandler
from azents.services.uploads.schema import (
    ImageFile,
    ImageThumbnails,
    StoredImage,
    StoredImageFile,
    UploadedImage,
)

from .data import (
    AdminNotFound,
    AgentAdminListOutput,
    AgentAdminOutput,
    AgentCreateInput,
    AgentDecommissionOutput,
    AgentListOutput,
    AgentOutput,
    AgentUpdateInput,
    AvatarUploadRejected,
    AvatarUploadTicketOutput,
    DuplicateAdmin,
    InvalidModelParameters,
    InvalidSelectableModelOptions,
    LastAdminCannotBeRemoved,
    ModelRequired,
    ModelSelectionNotFound,
    NotAdmin,
    NotBelongToWorkspace,
    PrivateAgentAccessDenied,
    UnlimitedRetention,
    WorkspaceUserNotFound,
)


def _get_avatar_handler() -> AvatarUploadHandler:
    """AvatarUploadHandler DI (stateless singleton)."""
    return AvatarUploadHandler()


def _get_workspace_s3_bucket(
    config: Annotated[Config, Depends(get_config)],
) -> str:
    """Workspace S3 bucket name DI."""
    return config.workspace_s3.bucket


def _get_avatar_cdn_base_url(
    config: Annotated[Config, Depends(get_config)],
) -> str | None:
    """Avatar CDN base URL DI (optional)."""
    return config.avatar_cdn_base_url


def _get_runtime_default_provider_id(
    config: Annotated[Config, Depends(get_config)],
) -> str | None:
    """Agent Runtime default Provider ID DI (optional)."""
    return config.runtime.default_provider_id


@dataclasses.dataclass
class AgentService:
    """Agent CRUD service."""

    repository: Annotated[AgentRepository, Depends(AgentRepository)]
    admin_repository: Annotated[AgentAdminRepository, Depends(AgentAdminRepository)]
    workspace_model_settings_repository: Annotated[
        WorkspaceModelSettingsRepository, Depends(WorkspaceModelSettingsRepository)
    ]
    model_catalog_read_service: Annotated[ModelCatalogReadService, Depends()]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_decommission_repository: Annotated[
        AgentDecommissionRepository, Depends(AgentDecommissionRepository)
    ]
    archived_session_retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    upload_service: Annotated[UploadService, Depends(get_upload_service)]
    avatar_handler: Annotated[AvatarUploadHandler, Depends(_get_avatar_handler)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    workspace_s3_bucket: Annotated[str, Depends(_get_workspace_s3_bucket)]
    avatar_cdn_base_url: Annotated[str | None, Depends(_get_avatar_cdn_base_url)]
    runtime_default_provider_id: Annotated[
        str | None,
        Depends(_get_runtime_default_provider_id),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    def _parse_model_parameters(
        self,
        params: ModelParameters | None,
    ) -> Result[ModelParameters | None, InvalidModelParameters]:
        """Validate Model parameter payload."""
        if params is None:
            return Success(None)
        try:
            return Success(
                ModelParameters.model_validate(params.model_dump(mode="json"))
            )
        except ValidationError as e:
            return Failure(
                InvalidModelParameters(errors=[error["msg"] for error in e.errors()])
            )

    async def _resolve_model_selection_input(
        self,
        workspace_id: str,
        selection_input: AgentModelSelectionInput,
    ) -> Result[AgentModelSelection, ModelSelectionNotFound]:
        """Convert model selection input to stored catalog snapshot."""
        result = await self.model_catalog_read_service.resolve_agent_model_selection(
            workspace_id=workspace_id,
            selection_input=selection_input,
        )
        match result:
            case Success(value):
                return Success(value)
            case Failure(_):
                return Failure(
                    ModelSelectionNotFound(
                        llm_provider_integration_id=(
                            selection_input.llm_provider_integration_id
                        ),
                        model_identifier=selection_input.model_identifier,
                    )
                )
            case _:
                assert_never(result)

    async def _normalize_option_inputs(
        self,
        workspace_id: str,
        option_inputs: list[SelectableModelOptionInput],
        *,
        main_model_label: str | None,
        lightweight_model_label: str | None,
    ) -> Result[
        NormalizedSelectableModelOptions,
        InvalidSelectableModelOptions | ModelSelectionNotFound,
    ]:
        """Normalize selectable option inputs into stored model snapshots."""

        async def resolve_option(
            option_input: SelectableModelOptionInput,
        ) -> Result[AgentModelSelection, ModelSelectionNotFound]:
            return await self._resolve_model_selection_input(
                workspace_id,
                option_input.model_selection,
            )

        result = await normalize_selectable_model_options(
            option_inputs=option_inputs,
            main_model_label=main_model_label,
            lightweight_model_label=lightweight_model_label,
            resolve_model_selection=resolve_option,
        )
        match result:
            case Success(value):
                return Success(value)
            case Failure(error):
                if isinstance(error, list):
                    return Failure(InvalidSelectableModelOptions(errors=error))
                return Failure(error)
            case _:
                assert_never(result)

    async def _resolve_create_model_options(
        self,
        create: AgentCreateInput,
    ) -> Result[
        NormalizedSelectableModelOptions,
        ModelRequired | ModelSelectionNotFound | InvalidSelectableModelOptions,
    ]:
        """Decide selectable model options for Agent creation."""
        async with self.session_manager() as session:
            settings = await self.workspace_model_settings_repository.get_or_create(
                session,
                create.workspace_id,
            )

        if create.selectable_model_options is not None:
            options_result = await self._normalize_option_inputs(
                create.workspace_id,
                create.selectable_model_options,
                main_model_label=create.main_model_label,
                lightweight_model_label=create.lightweight_model_label,
            )
            match options_result:
                case Success(value):
                    return Success(value)
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(options_result)

        if create.model_selection is not None:
            main_result = await self._resolve_model_selection_input(
                create.workspace_id,
                create.model_selection,
            )
            match main_result:
                case Success(value):
                    main_selection = value
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(main_result)
            if create.lightweight_model_selection is not None:
                lw_result = await self._resolve_model_selection_input(
                    create.workspace_id,
                    create.lightweight_model_selection,
                )
                match lw_result:
                    case Success(value):
                        lightweight_selection = value
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(lw_result)
            elif settings.default_lightweight_model_selection is not None:
                lightweight_selection = settings.default_lightweight_model_selection
            else:
                lightweight_selection = main_selection
            return Success(
                build_legacy_selectable_model_options(
                    model_selection=main_selection,
                    lightweight_model_selection=lightweight_selection,
                    main_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                    lightweight_label=DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
                )
            )

        if settings.default_selectable_model_options is not None:
            labels = {
                option.label for option in settings.default_selectable_model_options
            }
            main_label = (
                settings.default_main_model_label
                if settings.default_main_model_label in labels
                else settings.default_selectable_model_options[0].label
            )
            lightweight_label = (
                settings.default_lightweight_model_label
                if settings.default_lightweight_model_label in labels
                else settings.default_selectable_model_options[0].label
            )
            option_by_label = {
                option.label: option
                for option in settings.default_selectable_model_options
            }
            return Success(
                NormalizedSelectableModelOptions(
                    selectable_model_options=list(
                        settings.default_selectable_model_options
                    ),
                    main_model_label=main_label,
                    lightweight_model_label=lightweight_label,
                    model_selection=option_by_label[main_label].model_selection,
                    lightweight_model_selection=option_by_label[
                        lightweight_label
                    ].model_selection,
                )
            )

        if settings.default_model_selection is not None:
            return Success(
                build_legacy_selectable_model_options(
                    model_selection=settings.default_model_selection,
                    lightweight_model_selection=(
                        settings.default_lightweight_model_selection
                        or settings.default_model_selection
                    ),
                    main_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                    lightweight_label=DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
                )
            )

        return Failure(ModelRequired(workspace_id=create.workspace_id))

    async def create(
        self,
        create: AgentCreateInput,
        *,
        creator_workspace_user_id: str,
    ) -> Result[
        AgentOutput,
        ModelRequired
        | ModelSelectionNotFound
        | InvalidSelectableModelOptions
        | InvalidModelParameters,
    ]:
        """Create Agent and add creator as first admin."""
        selections_result = await self._resolve_create_model_options(create)
        match selections_result:
            case Success(value):
                model_options = value
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(selections_result)
        main_selection = model_options.model_selection
        lightweight_selection = model_options.lightweight_model_selection

        params_result = self._parse_model_parameters(create.model_parameters)
        match params_result:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(params_result)

        repo_create = AgentCreate(
            workspace_id=create.workspace_id,
            name=create.name,
            model_selection=main_selection,
            lightweight_model_selection=lightweight_selection,
            selectable_model_options=model_options.selectable_model_options,
            main_model_label=model_options.main_model_label,
            lightweight_model_label=model_options.lightweight_model_label,
            description=create.description,
            model_parameters=create.model_parameters,
            system_prompt=create.system_prompt,
            enabled=create.enabled,
            type=create.type,
            runtime_provider_id=(
                create.runtime_provider_id or self.runtime_default_provider_id
            ),
            shell_enabled=create.shell_enabled,
            memory_enabled=create.memory_enabled,
            tool_search_enabled=create.tool_search_enabled,
            max_turns=create.max_turns,
            subagent_settings=create.subagent_settings,
        )
        async with self.session_manager() as session:
            if create.model_selection is not None:
                set_default = (
                    self.workspace_model_settings_repository.set_default_model_if_empty
                )
                await set_default(session, create.workspace_id, main_selection)
            agent = await self.repository.create(session, repo_create)
            await self.admin_repository.create(
                session,
                AgentAdminCreate(
                    agent_id=agent.id,
                    workspace_user_id=creator_workspace_user_id,
                ),
            )
        return Success(await self._build_output(agent))

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> AgentListOutput:
        """Fetch Agent list in workspace."""
        async with self.session_manager() as session:
            if role == WorkspaceUserRole.OWNER:
                result = await self.repository.list_by_workspace(session, workspace_id)
            else:
                result = await self.repository.list_visible_by_workspace(
                    session, workspace_id, workspace_user_id
                )
        items = [await self._build_output(a) for a in result.items]
        return AgentListOutput(items=items)

    async def get_by_id(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentOutput,
        NotFound | NotBelongToWorkspace | PrivateAgentAccessDenied,
    ]:
        """Fetch Agent by ID."""
        async with self.session_manager() as session:
            agent = await self.repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(NotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        if agent.type == AgentType.PRIVATE and role != WorkspaceUserRole.OWNER:
            async with self.session_manager() as session:
                is_admin = await self.admin_repository.is_admin(
                    session, agent_id, workspace_user_id
                )
            if not is_admin:
                return Failure(PrivateAgentAccessDenied(agent_id=agent_id))
        return Success(await self._build_output(agent))

    async def update_by_id(
        self,
        agent_id: str,
        update: AgentUpdateInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentOutput,
        NotFound
        | NotBelongToWorkspace
        | NotAdmin
        | ModelRequired
        | ModelSelectionNotFound
        | InvalidSelectableModelOptions
        | InvalidModelParameters,
    ]:
        """Update Agent by ID."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, agent_id)
        if existing is None:
            return Failure(NotFound(agent_id=agent_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))

        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)

        repo_update = AgentUpdate()
        if "name" in update:
            repo_update["name"] = update["name"]
        if "description" in update:
            repo_update["description"] = update["description"]

        model_options = normalize_stored_selectable_model_options(
            selectable_model_options=existing.selectable_model_options,
            main_model_label=existing.main_model_label,
            lightweight_model_label=existing.lightweight_model_label,
        )
        if "selectable_model_options" in update:
            option_inputs = update["selectable_model_options"]
            if option_inputs is None:
                return Failure(ModelRequired(workspace_id=workspace_id))
            options_result = await self._normalize_option_inputs(
                workspace_id,
                option_inputs,
                main_model_label=update.get(
                    "main_model_label", existing.main_model_label
                ),
                lightweight_model_label=update.get(
                    "lightweight_model_label", existing.lightweight_model_label
                ),
            )
            match options_result:
                case Success(value):
                    model_options = value
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(options_result)
        elif "model_selection" in update or "lightweight_model_selection" in update:
            main_selection = existing.model_selection
            if "model_selection" in update:
                selection_input = update["model_selection"]
                if selection_input is None:
                    async with self.session_manager() as session:
                        settings = await self.workspace_model_settings_repository.get(
                            session,
                            workspace_id,
                        )
                    if settings is None or settings.default_model_selection is None:
                        return Failure(ModelRequired(workspace_id=workspace_id))
                    main_selection = settings.default_model_selection
                else:
                    main_result = await self._resolve_model_selection_input(
                        workspace_id,
                        selection_input,
                    )
                    match main_result:
                        case Success(value):
                            main_selection = value
                        case Failure(error):
                            return Failure(error)
                        case _:
                            assert_never(main_result)

            lightweight_selection = existing.lightweight_model_selection
            if "lightweight_model_selection" in update:
                selection_input = update["lightweight_model_selection"]
                if selection_input is None:
                    lightweight_selection = main_selection
                else:
                    lw_result = await self._resolve_model_selection_input(
                        workspace_id,
                        selection_input,
                    )
                    match lw_result:
                        case Success(value):
                            lightweight_selection = value
                        case Failure(error):
                            return Failure(error)
                        case _:
                            assert_never(lw_result)
            model_options = build_legacy_selectable_model_options(
                model_selection=main_selection,
                lightweight_model_selection=lightweight_selection,
                main_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                lightweight_label=DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
            )
        elif "main_model_label" in update or "lightweight_model_label" in update:
            model_options = normalize_stored_selectable_model_options(
                selectable_model_options=existing.selectable_model_options,
                main_model_label=update.get(
                    "main_model_label", existing.main_model_label
                ),
                lightweight_model_label=update.get(
                    "lightweight_model_label", existing.lightweight_model_label
                ),
            )

        repo_update["model_selection"] = model_options.model_selection
        repo_update["lightweight_model_selection"] = (
            model_options.lightweight_model_selection
        )
        repo_update["selectable_model_options"] = model_options.selectable_model_options
        repo_update["main_model_label"] = model_options.main_model_label
        repo_update["lightweight_model_label"] = model_options.lightweight_model_label

        model_parameters = update.get("model_parameters", existing.model_parameters)
        params_result = self._parse_model_parameters(model_parameters)
        match params_result:
            case Success():
                pass
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(params_result)
        if "model_parameters" in update:
            repo_update["model_parameters"] = update["model_parameters"]

        for key in (
            "system_prompt",
            "enabled",
            "type",
            "runtime_provider_id",
            "shell_enabled",
            "memory_enabled",
            "tool_search_enabled",
            "max_turns",
            "subagent_settings",
        ):
            if key in update:
                repo_update[key] = update[key]  # type: ignore[literal-required]

        async with self.session_manager() as session:
            result = await self.repository.update_by_id(session, agent_id, repo_update)
        match result:
            case Success(value):
                return Success(await self._build_output(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def delete_by_id(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentDecommissionOutput,
        NotFound | NotBelongToWorkspace | NotAdmin | UnlimitedRetention,
    ]:
        """Request durable Agent decommission."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, agent_id)
        if existing is None:
            return Failure(NotFound(agent_id=agent_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        async with self.session_manager() as session:
            settings = await self.archived_session_retention_repository.lock_settings(
                session
            )
            if settings.archived_session_retention_days is None:
                return Failure(UnlimitedRetention(agent_id=agent_id))
            decommissioned = await self.repository.mark_decommissioning(
                session,
                agent_id,
            )
            if decommissioned is None:
                return Failure(NotFound(agent_id=agent_id))
            job = await self.agent_decommission_repository.create_or_get(
                session,
                agent_id=decommissioned.id,
                workspace_id=decommissioned.workspace_id,
                requested_by_workspace_user_id=workspace_user_id,
            )
        return Success(AgentDecommissionOutput(job=job))

    async def list_admins(
        self,
        agent_id: str,
        *,
        workspace_id: str,
    ) -> Result[AgentAdminListOutput, NotFound | NotBelongToWorkspace]:
        """Fetch Agent admin list."""
        async with self.session_manager() as session:
            agent = await self.repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(NotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        async with self.session_manager() as session:
            admins = await self.admin_repository.list_by_agent(session, agent_id)
        return Success(
            AgentAdminListOutput(
                items=[
                    AgentAdminOutput(
                        id=a.id,
                        agent_id=a.agent_id,
                        workspace_user_id=a.workspace_user_id,
                        created_at=a.created_at,
                    )
                    for a in admins.items
                ]
            )
        )

    async def add_admin(
        self,
        agent_id: str,
        target_workspace_user_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentAdminOutput,
        NotFound
        | NotBelongToWorkspace
        | NotAdmin
        | DuplicateAdmin
        | WorkspaceUserNotFound,
    ]:
        """Add admin to Agent."""
        async with self.session_manager() as session:
            agent = await self.repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(NotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        async with self.session_manager() as session:
            target_user = await self.workspace_user_repository.get(
                session, target_workspace_user_id
            )
        if target_user is None or target_user.workspace_id != workspace_id:
            return Failure(
                WorkspaceUserNotFound(workspace_user_id=target_workspace_user_id)
            )
        async with self.session_manager() as session:
            result = await self.admin_repository.create(
                session,
                AgentAdminCreate(
                    agent_id=agent_id,
                    workspace_user_id=target_workspace_user_id,
                ),
            )
        match result:
            case Success(value):
                return Success(
                    AgentAdminOutput(
                        id=value.id,
                        agent_id=value.agent_id,
                        workspace_user_id=value.workspace_user_id,
                        created_at=value.created_at,
                    )
                )
            case Failure(error):
                return Failure(
                    DuplicateAdmin(
                        agent_id=error.agent_id,
                        workspace_user_id=error.workspace_user_id,
                    )
                )
            case _:
                assert_never(result)

    async def remove_admin(
        self,
        agent_id: str,
        target_workspace_user_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        None,
        NotFound
        | NotBelongToWorkspace
        | NotAdmin
        | LastAdminCannotBeRemoved
        | AdminNotFound,
    ]:
        """Remove admin from Agent."""
        async with self.session_manager() as session:
            agent = await self.repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(NotFound(agent_id=agent_id))
        if agent.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        async with self.session_manager() as session:
            count = await self.admin_repository.count_by_agent(session, agent_id)
            if count <= 1:
                return Failure(
                    LastAdminCannotBeRemoved(
                        agent_id=agent_id,
                        workspace_user_id=target_workspace_user_id,
                    )
                )
            deleted = await self.admin_repository.delete(
                session, agent_id, target_workspace_user_id
            )
        if not deleted:
            return Failure(
                AdminNotFound(
                    agent_id=agent_id,
                    workspace_user_id=target_workspace_user_id,
                )
            )
        return Success(None)

    async def request_avatar_upload(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        content_type: str,
        content_length: int,
    ) -> Result[
        AvatarUploadTicketOutput,
        NotFound | NotBelongToWorkspace | NotAdmin | AvatarUploadRejected,
    ]:
        """Issue presigned PUT ticket for avatar upload."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, agent_id)
        if existing is None:
            return Failure(NotFound(agent_id=agent_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        try:
            ticket = await self.upload_service.issue_upload_ticket(
                category=AvatarUploadHandler.category,
                owner_id=agent_id,
                content_type=content_type,
                content_length=content_length,
            )
        except UploadValidationError as err:
            return Failure(AvatarUploadRejected(message=str(err)))
        return Success(
            AvatarUploadTicketOutput(
                upload_key=ticket.upload_key,
                upload_url=ticket.upload_url,
                expires_at=ticket.expires_at,
            )
        )

    async def finalize_avatar(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        upload_key: str,
        filename: str,
    ) -> Result[
        AgentOutput,
        NotFound | NotBelongToWorkspace | NotAdmin | AvatarUploadRejected,
    ]:
        """Validate uploaded avatar file and reflect it in DB."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, agent_id)
        if existing is None:
            return Failure(NotFound(agent_id=agent_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        try:
            stored = await self.upload_service.finalize(
                category=AvatarUploadHandler.category,
                owner_id=agent_id,
                upload_key=upload_key,
                filename=filename,
            )
        except UploadValidationError as err:
            return Failure(AvatarUploadRejected(message=str(err)))
        async with self.session_manager() as session:
            update_result = await self.repository.update_avatar(
                session, agent_id, stored
            )
        match update_result:
            case Success(updated_agent):
                pass
            case Failure(_):
                return Failure(NotFound(agent_id=agent_id))
        if existing.avatar is not None:
            try:
                await self.avatar_handler.delete_files(
                    existing.avatar,
                    self.s3_service,
                    self.workspace_s3_bucket,
                )
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        return Success(await self._build_output(updated_agent))

    async def remove_avatar(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[AgentOutput, NotFound | NotBelongToWorkspace | NotAdmin]:
        """Remove Avatar and delete S3 files."""
        async with self.session_manager() as session:
            existing = await self.repository.get_by_id(session, agent_id)
        if existing is None:
            return Failure(NotFound(agent_id=agent_id))
        if existing.workspace_id != workspace_id:
            return Failure(NotBelongToWorkspace(agent_id=agent_id))
        admin_check = await self._check_admin_or_owner(
            agent_id, workspace_user_id, role
        )
        if admin_check is not None:
            return Failure(admin_check)
        async with self.session_manager() as session:
            update_result = await self.repository.update_avatar(session, agent_id, None)
        match update_result:
            case Success(updated_agent):
                pass
            case Failure(_):
                return Failure(NotFound(agent_id=agent_id))
        if existing.avatar is not None:
            try:
                await self.avatar_handler.delete_files(
                    existing.avatar,
                    self.s3_service,
                    self.workspace_s3_bucket,
                )
            except Exception:  # noqa: BLE001
                pass
        return Success(await self._build_output(updated_agent))

    async def _build_output(self, agent: Agent) -> AgentOutput:
        """Convert `Agent` domain model to output."""
        avatar = await self._resolve_avatar(agent.avatar)
        context_window = self._compute_effective_context_window(agent)
        return AgentOutput.convert_from(
            agent,
            avatar=avatar,
            effective_context_window_tokens=(
                context_window.effective_max_input_tokens
                if context_window is not None
                else None
            ),
            effective_auto_compaction_threshold_tokens=(
                context_window.auto_compaction_threshold_tokens
                if context_window is not None
                else None
            ),
        )

    def _compute_effective_context_window(
        self,
        agent: Agent,
    ) -> EffectiveContextWindow | None:
        """Calculate effective context window using same criteria as Runtime."""
        option_by_label = {
            option.label: option for option in agent.selectable_model_options
        }
        main_option = option_by_label.get(agent.main_model_label)
        lightweight_option = option_by_label.get(agent.lightweight_model_label)
        if main_option is None or lightweight_option is None:
            return None

        main_max_input_tokens = get_max_input_tokens(
            main_option.model_selection.normalized_capabilities.context_window.max_input_tokens,
            to_runtime_model(
                main_option.model_selection.provider,
                main_option.model_selection.model_identifier,
            ),
        )
        compaction_max_input_tokens = get_max_input_tokens(
            lightweight_option.model_selection.normalized_capabilities.context_window.max_input_tokens,
            to_runtime_model(
                lightweight_option.model_selection.provider,
                lightweight_option.model_selection.model_identifier,
            ),
        )
        if lightweight_option.settings.context_window_tokens is not None:
            compaction_max_input_tokens = min(
                compaction_max_input_tokens,
                lightweight_option.settings.context_window_tokens,
            )
        return compute_effective_context_window_tokens(
            main_max_input_tokens=main_max_input_tokens,
            compaction_max_input_tokens=compaction_max_input_tokens,
            context_window_tokens=main_option.settings.context_window_tokens,
        )

    async def _resolve_avatar(self, stored: StoredImage | None) -> UploadedImage | None:
        """Convert StoredImage to UploadedImage."""
        if stored is None:
            return None
        return UploadedImage(
            filename=stored.filename,
            default=await self._resolve_file(stored.default),
            thumbnails=ImageThumbnails(
                small=(
                    await self._resolve_file(stored.thumbnails.small)
                    if stored.thumbnails.small is not None
                    else None
                ),
                medium=(
                    await self._resolve_file(stored.thumbnails.medium)
                    if stored.thumbnails.medium is not None
                    else None
                ),
                large=(
                    await self._resolve_file(stored.thumbnails.large)
                    if stored.thumbnails.large is not None
                    else None
                ),
            ),
            uploaded_at=stored.uploaded_at,
        )

    async def _resolve_file(self, stored: StoredImageFile) -> ImageFile:
        """Convert StoredImageFile to ImageFile."""
        if self.avatar_cdn_base_url is not None:
            url = f"{self.avatar_cdn_base_url}/{stored.key}"
        else:
            url = await self.s3_service.get_download_url(
                bucket=self.workspace_s3_bucket,
                key=stored.key,
                expires_in=datetime.timedelta(hours=1),
            )
        width = stored.width if stored.width is not None else 0
        height = stored.height if stored.height is not None else 0
        return ImageFile(url=url, width=width, height=height)

    async def _check_admin_or_owner(
        self,
        agent_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> NotAdmin | None:
        """Check whether admin or owner."""
        if role == WorkspaceUserRole.OWNER:
            return None
        async with self.session_manager() as session:
            is_admin = await self.admin_repository.is_admin(
                session, agent_id, workspace_user_id
            )
        if not is_admin:
            return NotAdmin(agent_id=agent_id)
        return None
