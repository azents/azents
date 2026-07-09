"""AgentSession input enqueue facade."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectDefaultItemType,
    AgentSessionKind,
    AgentSessionStatus,
    InputBufferKind,
)
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.run.input import InputMessage
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_default.data import AgentProjectDefaultCreate
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService
from azents.services.session_git_worktree import (
    ExistingProjectWorkspaceItem,
    GitWorktreeWorkspaceItem,
    NewSessionWorkspaceItem,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
    normalize_session_workspace_project_paths,
)


@dataclasses.dataclass(frozen=True)
class BufferedAgentSessionInputResult:
    """InputBuffer creation and broker wake-up result."""

    agent_runtime_id: str
    agent_session_id: str
    input_buffer: InputBuffer


@dataclasses.dataclass(frozen=True)
class CreatedAgentSessionInputResult:
    """New AgentSession creation and first input enqueue result."""

    agent_runtime_id: str
    agent_session: AgentSession
    input_buffer: InputBuffer


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSessionNotFound:
    """Requested AgentSession was not found."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputWrongAgent:
    """Requested AgentSession does not belong to the requested agent."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputInactiveSession:
    """Requested AgentSession is not writable."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSubagentReadOnly:
    """Requested child subagent session does not accept direct human input."""


AgentSessionInputError = (
    AgentSessionInputSessionNotFound
    | AgentSessionInputWrongAgent
    | AgentSessionInputInactiveSession
    | AgentSessionInputSubagentReadOnly
    | InvalidProjectPath
)


@dataclasses.dataclass
class AgentSessionInputService:
    """Input enqueue facade based on AgentSession."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_project_preset_repository: Annotated[
        AgentProjectPresetRepository,
        Depends(AgentProjectPresetRepository),
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    agent_project_default_repository: Annotated[
        AgentProjectDefaultRepository,
        Depends(AgentProjectDefaultRepository),
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create_buffered_agent_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        message: InputMessage,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Store user input as durable InputBuffer row."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, agent_session_id
            )
            if agent_session is None:
                return Failure(AgentSessionInputSessionNotFound())
            if agent_session.agent_id != agent_id:
                return Failure(AgentSessionInputWrongAgent())
            if agent_session.status != AgentSessionStatus.ACTIVE:
                return Failure(AgentSessionInputInactiveSession())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(AgentSessionInputSubagentReadOnly())

            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            input_buffer = await self._enqueue_user_message(
                session,
                agent_session=agent_session,
                message=message,
                user_id=user_id,
                client_request_id=client_request_id,
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                agent_session.id,
            )

        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session_id=agent_session.id,
                input_buffer=input_buffer,
            )
        )

    async def create_buffered_agent_action_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        action: dict[str, JSONValue],
        message: InputMessage,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Store user action input as durable InputBuffer row."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, agent_session_id
            )
            if agent_session is None:
                return Failure(AgentSessionInputSessionNotFound())
            if agent_session.agent_id != agent_id:
                return Failure(AgentSessionInputWrongAgent())
            if agent_session.status != AgentSessionStatus.ACTIVE:
                return Failure(AgentSessionInputInactiveSession())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(AgentSessionInputSubagentReadOnly())

            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            result = await self.input_buffer_service.enqueue(
                session,
                InputBufferEnqueue(
                    session_id=agent_session.id,
                    kind=InputBufferKind.ACTION_MESSAGE,
                    actor_user_id=user_id,
                    content=message.text,
                    idempotency_key=client_request_id,
                    metadata=message.metadata,
                    action=action,
                    attachments=message.attachments,
                    file_parts=message.file_parts,
                ),
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                agent_session.id,
            )

        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session_id=agent_session.id,
                input_buffer=result.input_buffer,
            )
        )

    async def create_team_session_with_buffered_input(
        self,
        *,
        agent_id: str,
        message: InputMessage,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
        client_request_id: str | None = None,
    ) -> Result[CreatedAgentSessionInputResult, AgentSessionInputError]:
        """Create a non-primary team AgentSession and store first user input."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentSessionInputSessionNotFound())
            if not await self._has_workspace_access(
                session,
                workspace_id=agent.workspace_id,
                user_id=user_id,
            ):
                return Failure(AgentSessionInputSessionNotFound())
            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            ensure_primary = self.agent_session_repository.ensure_team_primary_for_agent
            await ensure_primary(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            workspace_items_result = self._workspace_items_from_request(
                existing_project_paths=existing_project_paths,
                setup_actions=setup_actions,
            )
            match workspace_items_result:
                case Success(workspace_items):
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(workspace_items_result)
            agent_session = await self.agent_session_repository.create(
                session,
                AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                ),
            )
            workspace_result = await self._create_session_workspace_items(
                session,
                agent_id=agent_id,
                session_id=agent_session.id,
                session_handle=agent_session.handle,
                workspace_items=workspace_items,
            )
            match workspace_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(workspace_result)
            await self._enqueue_setup_actions(
                session,
                agent_session=agent_session,
                workspace_items=workspace_items,
                message=message,
                user_id=user_id,
                client_request_id=client_request_id,
            )
            input_buffer = await self._enqueue_user_message(
                session,
                agent_session=agent_session,
                message=message,
                user_id=user_id,
                client_request_id=client_request_id,
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                agent_session.id,
            )

        return Success(
            CreatedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session=agent_session,
                input_buffer=input_buffer,
            )
        )

    async def _enqueue_setup_actions(
        self,
        session: AsyncSession,
        *,
        agent_session: AgentSession,
        workspace_items: list[NewSessionWorkspaceItem],
        message: InputMessage,
        user_id: str,
        client_request_id: str | None,
    ) -> None:
        """Enqueue ordered setup TurnActions before the first user message."""
        for index, item in enumerate(workspace_items):
            match item:
                case ExistingProjectWorkspaceItem():
                    continue
                case GitWorktreeWorkspaceItem(
                    source_project_path=source_project_path,
                    starting_ref=starting_ref,
                ):
                    action = CreateGitWorktreeAction(
                        source_project_path=source_project_path,
                        starting_ref=starting_ref,
                    )
                    await self.input_buffer_service.enqueue(
                        session,
                        InputBufferEnqueue(
                            session_id=agent_session.id,
                            kind=InputBufferKind.ACTION_MESSAGE,
                            actor_user_id=user_id,
                            content="",
                            idempotency_key=(
                                f"{client_request_id}:setup:{index}"
                                if client_request_id is not None
                                else None
                            ),
                            metadata=message.metadata,
                            action=action.model_dump(mode="json"),
                            attachments=[],
                            file_parts=[],
                        ),
                    )
                case _:
                    assert_never(item)

    async def _enqueue_user_message(
        self,
        session: AsyncSession,
        *,
        agent_session: AgentSession,
        message: InputMessage,
        user_id: str,
        client_request_id: str | None,
    ) -> InputBuffer:
        """Enqueue one user message for an already selected AgentSession."""
        result = await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=agent_session.id,
                kind=InputBufferKind.USER_MESSAGE,
                actor_user_id=user_id,
                content=message.text,
                idempotency_key=client_request_id,
                metadata=message.metadata,
                action=None,
                attachments=message.attachments,
                file_parts=message.file_parts,
            ),
        )
        return result.input_buffer

    def _workspace_items_from_request(
        self,
        *,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
    ) -> Result[list[NewSessionWorkspaceItem], InvalidProjectPath]:
        """Normalize direct Project paths and ordered setup actions."""
        try:
            normalized_project_paths = normalize_session_workspace_project_paths(
                existing_project_paths
            )
        except ValueError as exc:
            return Failure(InvalidProjectPath(path="", reason=str(exc)))

        workspace_items: list[NewSessionWorkspaceItem] = [
            ExistingProjectWorkspaceItem(path=path) for path in normalized_project_paths
        ]
        for action in setup_actions:
            try:
                normalized_source_path = normalize_session_workspace_path(
                    action.source_project_path
                )
            except ValueError as exc:
                return Failure(
                    InvalidProjectPath(
                        path=action.source_project_path,
                        reason=str(exc),
                    )
                )
            starting_ref = action.starting_ref.strip()
            if not starting_ref:
                return Failure(
                    InvalidProjectPath(
                        path=normalized_source_path,
                        reason="Starting Git ref is required.",
                    )
                )
            workspace_items.append(
                GitWorktreeWorkspaceItem(
                    source_project_path=normalized_source_path,
                    starting_ref=starting_ref,
                )
            )
        return Success(_dedupe_existing_project_items(workspace_items))

    async def _create_session_workspace_items(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        session_handle: str,
        workspace_items: list[NewSessionWorkspaceItem],
    ) -> Result[None, InvalidProjectPath]:
        """Create direct Project rows and queue selected worktree items."""
        existing_project_paths = [
            item.path
            for item in workspace_items
            if isinstance(item, ExistingProjectWorkspaceItem)
        ]
        worktree_items = [
            item
            for item in workspace_items
            if isinstance(item, GitWorktreeWorkspaceItem)
        ]
        project_repository = self.session_workspace_project_repository
        for path in existing_project_paths:
            await project_repository.create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=session_id,
                    path=path,
                ),
            )
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=path,
            )
            await self.agent_project_catalog_repository.upsert_entry(
                session,
                agent_id=agent_id,
                path=path,
            )
        for item in worktree_items:
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=item.source_project_path,
            )
        if workspace_items:
            await self.agent_project_default_repository.replace_default_items(
                session,
                agent_id=agent_id,
                items=[
                    _default_item_from_workspace_item(item) for item in workspace_items
                ],
            )
        return Success(None)

    async def _create_session_projects(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        project_paths: list[str],
    ) -> None:
        """Create session Project rows and refresh Agent Project presets."""
        workspace_result = await self._create_session_workspace_items(
            session,
            agent_id=agent_id,
            session_id=session_id,
            session_handle="",
            workspace_items=[
                ExistingProjectWorkspaceItem(path=path) for path in project_paths
            ],
        )
        match workspace_result:
            case Success():
                return
            case Failure(error):
                raise ValueError(error.reason)
            case _:
                assert_never(workspace_result)

    async def _has_workspace_access(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """Return whether the user is a member of the workspace."""
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return workspace_user is not None


def _dedupe_existing_project_items(
    items: list[NewSessionWorkspaceItem],
) -> list[NewSessionWorkspaceItem]:
    """Deduplicate exact existing Project rows while preserving worktree items."""
    seen_project_paths: set[str] = set()
    deduped: list[NewSessionWorkspaceItem] = []
    for item in items:
        match item:
            case ExistingProjectWorkspaceItem(path=path):
                if path in seen_project_paths:
                    continue
                seen_project_paths.add(path)
                deduped.append(item)
            case GitWorktreeWorkspaceItem():
                deduped.append(item)
            case _:
                assert_never(item)
    return deduped


def _default_item_from_workspace_item(
    item: NewSessionWorkspaceItem,
) -> AgentProjectDefaultCreate:
    """Convert a selected workspace item to reusable default metadata."""
    match item:
        case ExistingProjectWorkspaceItem(path=path):
            return AgentProjectDefaultCreate(
                path=path,
                item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
            )
        case GitWorktreeWorkspaceItem(source_project_path=source_project_path):
            return AgentProjectDefaultCreate(
                path=source_project_path,
                item_type=AgentProjectDefaultItemType.GIT_WORKTREE,
            )
        case _:
            assert_never(item)
