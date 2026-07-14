"""AgentSession input enqueue facade."""

import dataclasses
import datetime
import hashlib
import json
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectDefaultItemType,
    AgentSessionKind,
    AgentSessionStatus,
    InputBufferKind,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.run.input import InputMessage
from azents.rdb.deps import get_session_manager
from azents.rdb.models.chat_write_request import ChatWriteRequestType
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
from azents.repos.agent_session_create_request.data import (
    AgentSessionCreateRequestClaim,
    AgentSessionCreateRequestRecord,
)
from azents.repos.agent_session_create_request.repository import (
    AgentSessionCreateRequestRepository,
)
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
from azents.repos.chat_write_request.repository import ChatWriteRequestRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.input_buffer.repository import InputBufferRepository
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
    input_buffer_pending: bool


@dataclasses.dataclass(frozen=True)
class CreatedAgentSessionInputResult:
    """New AgentSession creation and first input enqueue result."""

    agent_runtime_id: str
    agent_session: AgentSession
    input_buffer: InputBuffer
    input_buffer_pending: bool


@dataclasses.dataclass(frozen=True)
class CreatedAgentSessionRequestResources:
    """Durable resources recovered for a retried Session create request."""

    agent_session: AgentSession
    input_buffer: InputBuffer
    input_buffer_pending: bool


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSessionNotFound:
    """Requested AgentSession was not found."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputWrongAgent:
    """Requested AgentSession does not belong to the requested agent."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputAccessDenied:
    """Requesting user is no longer a member of the Session Workspace."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputInactiveSession:
    """Requested AgentSession is not writable."""


@dataclasses.dataclass(frozen=True)
class AgentSessionInputSubagentReadOnly:
    """Requested child subagent session does not accept direct human input."""


@dataclasses.dataclass(frozen=True)
class AgentSessionCreateRequestConflict:
    """A create-request key was already used for another semantic payload."""

    client_request_id: str


@dataclasses.dataclass(frozen=True)
class AgentSessionInputRequestConflict:
    """An existing-Session request key has different input semantics."""

    client_request_id: str


AgentSessionInputError = (
    AgentSessionInputSessionNotFound
    | AgentSessionInputWrongAgent
    | AgentSessionInputAccessDenied
    | AgentSessionInputInactiveSession
    | AgentSessionInputSubagentReadOnly
    | AgentSessionCreateRequestConflict
    | AgentSessionInputRequestConflict
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
    agent_session_create_request_repository: Annotated[
        AgentSessionCreateRequestRepository,
        Depends(AgentSessionCreateRequestRepository),
    ]
    chat_write_request_repository: Annotated[
        ChatWriteRequestRepository,
        Depends(ChatWriteRequestRepository),
    ]
    input_buffer_repository: Annotated[
        InputBufferRepository,
        Depends(InputBufferRepository),
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
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Store user input as durable InputBuffer row."""
        return await self._create_buffered_existing_session_input(
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            kind=InputBufferKind.USER_MESSAGE,
            action=None,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            client_request_id=client_request_id,
        )

    async def create_buffered_agent_action_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        action: dict[str, JSONValue],
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Store user action input as durable InputBuffer row."""
        return await self._create_buffered_existing_session_input(
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            kind=InputBufferKind.ACTION_MESSAGE,
            action=action,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            client_request_id=client_request_id,
        )

    async def _create_buffered_existing_session_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        kind: InputBufferKind,
        action: dict[str, JSONValue] | None,
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        client_request_id: str | None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Accept one existing-Session input under a durable request authority."""
        payload = _existing_session_input_semantic_payload(
            kind=kind,
            action=action,
            message=message,
            inference_profile=inference_profile,
        )
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.lock_by_id(
                session, agent_session_id
            )
            if agent_session is None:
                return Failure(AgentSessionInputSessionNotFound())
            if agent_session.agent_id != agent_id:
                return Failure(AgentSessionInputWrongAgent())
            workspace_user = (
                await self.workspace_user_repository.lock_by_workspace_and_user(
                    session,
                    agent_session.workspace_id,
                    user_id,
                )
            )
            if workspace_user is None:
                return Failure(AgentSessionInputAccessDenied())
            if agent_session.status != AgentSessionStatus.ACTIVE:
                return Failure(AgentSessionInputInactiveSession())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(AgentSessionInputSubagentReadOnly())

            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            enqueue = InputBufferEnqueue(
                session_id=agent_session.id,
                kind=kind,
                requested_model_target_label=inference_profile.model_target_label,
                requested_reasoning_effort=inference_profile.reasoning_effort,
                actor_user_id=user_id,
                content=message.text,
                idempotency_key=client_request_id,
                metadata=message.metadata,
                action=action,
                attachments=message.attachments,
                file_parts=message.file_parts,
            )

            if client_request_id is None:
                enqueue_result = await self.input_buffer_service.enqueue(
                    session,
                    enqueue,
                )
                input_buffer = enqueue_result.input_buffer
                input_buffer_pending = True
            else:
                create_result = (
                    await self.chat_write_request_repository.create_idempotent(
                        session,
                        ChatWriteRequestCreate(
                            session_id=agent_session.id,
                            user_id=user_id,
                            client_request_id=client_request_id,
                            write_type=ChatWriteRequestType.INPUT_BUFFER,
                            accepted_type=ChatWriteRequestType.INPUT_BUFFER,
                            accepted_id=uuid7().hex,
                            history_reload_required=False,
                            payload=payload,
                        ),
                    )
                )
                record = create_result.record
                if not _matches_existing_session_input_request(
                    record,
                    payload=payload,
                ):
                    return Failure(
                        AgentSessionInputRequestConflict(
                            client_request_id=client_request_id,
                        )
                    )
                if create_result.created:
                    enqueue_result = (
                        await self.input_buffer_service.enqueue_preallocated(
                            session,
                            enqueue,
                            input_buffer_id=record.accepted_id,
                        )
                    )
                    input_buffer = enqueue_result.input_buffer
                    input_buffer_pending = True
                else:
                    pending = await self.input_buffer_repository.get_by_id(
                        session,
                        record.accepted_id,
                    )
                    input_buffer_pending = pending is not None
                    input_buffer = pending or _reconstruct_accepted_input_buffer(
                        record,
                        kind=kind,
                        action=action,
                        message=message,
                        inference_profile=inference_profile,
                    )
            if input_buffer_pending:
                await self.agent_session_repository.mark_running_for_input_wakeup(
                    session,
                    agent_session.id,
                )

        return Success(
            BufferedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session_id=agent_session.id,
                input_buffer=input_buffer,
                input_buffer_pending=input_buffer_pending,
            )
        )

    async def create_team_session_with_buffered_input(
        self,
        *,
        agent_id: str,
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
        client_request_id: str | None = None,
    ) -> Result[CreatedAgentSessionInputResult, AgentSessionInputError]:
        """Create a non-primary team AgentSession and store first user input."""
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
        payload_hash = _new_session_semantic_payload_hash(
            message=message,
            inference_profile=inference_profile,
            workspace_items=workspace_items,
        )
        async with self.session_manager() as session:
            agent = await self.agent_repository.lock_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentSessionInputSessionNotFound())

            create_request = None
            create_request_claimed = False
            if client_request_id is not None:
                claim_result = await self.agent_session_create_request_repository.claim(
                    session,
                    AgentSessionCreateRequestClaim(
                        user_id=user_id,
                        agent_id=agent_id,
                        client_request_id=client_request_id,
                        payload_hash=payload_hash,
                    ),
                )
                create_request = claim_result.record
                create_request_claimed = claim_result.claimed
                if claim_result.claimed:
                    if create_request.payload_hash != payload_hash:
                        raise RuntimeError(
                            "New AgentSession create-request claim hash changed"
                        )
                else:
                    # Existing-session writes lock Session before WorkspaceUser.
                    # Keep a replay on the same order: locking membership before
                    # loading the completed Session would invert that order and can
                    # deadlock with a concurrent write to the created Session.
                    existing = await self._load_created_session_request_result(
                        session,
                        create_request=create_request,
                    )
                    if existing is None:
                        workspace_user = await (
                            self.workspace_user_repository.lock_by_workspace_and_user(
                                session,
                                agent.workspace_id,
                                user_id,
                            )
                        )
                        if workspace_user is None:
                            return Failure(AgentSessionInputAccessDenied())
                        if create_request.payload_hash != payload_hash:
                            return Failure(
                                AgentSessionCreateRequestConflict(
                                    client_request_id=client_request_id,
                                )
                            )
                        return Failure(AgentSessionInputInactiveSession())
                    if (
                        existing.agent_session.agent_id != agent_id
                        or existing.agent_session.workspace_id != agent.workspace_id
                    ):
                        raise RuntimeError(
                            "AgentSession create request points outside its Agent"
                        )
                    workspace_user = await (
                        self.workspace_user_repository.lock_by_workspace_and_user(
                            session,
                            existing.agent_session.workspace_id,
                            user_id,
                        )
                    )
                    if workspace_user is None:
                        return Failure(AgentSessionInputAccessDenied())
                    if create_request.payload_hash != payload_hash:
                        return Failure(
                            AgentSessionCreateRequestConflict(
                                client_request_id=client_request_id,
                            )
                        )
                    agent_session = existing.agent_session
                    input_buffer = existing.input_buffer
                    input_buffer_pending = existing.input_buffer_pending
                    if agent_session.status is not AgentSessionStatus.ACTIVE:
                        return Failure(AgentSessionInputInactiveSession())
                    runtime = await self.agent_runtime_repository.ensure_for_agent(
                        session,
                        agent_id,
                    )
                    if input_buffer_pending:
                        await (
                            self.agent_session_repository.mark_running_for_input_wakeup(
                                session,
                                agent_session.id,
                            )
                        )
                    return Success(
                        CreatedAgentSessionInputResult(
                            agent_runtime_id=runtime.id,
                            agent_session=agent_session,
                            input_buffer=input_buffer,
                            input_buffer_pending=input_buffer_pending,
                        )
                    )

            workspace_user = (
                await self.workspace_user_repository.lock_by_workspace_and_user(
                    session,
                    agent.workspace_id,
                    user_id,
                )
            )
            if workspace_user is None:
                if create_request is not None and create_request_claimed:
                    create_request_repository = (
                        self.agent_session_create_request_repository
                    )
                    await create_request_repository.abandon_pending_claim(
                        session,
                        request_id=create_request.id,
                    )
                return Failure(AgentSessionInputAccessDenied())

            runtime = await self.agent_runtime_repository.ensure_for_agent(
                session, agent_id
            )
            ensure_primary = self.agent_session_repository.ensure_team_primary_for_agent
            await ensure_primary(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
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
                    raise RuntimeError(
                        "Normalized AgentSession workspace items became invalid: "
                        f"{error.reason}"
                    )
                case _:
                    assert_never(workspace_result)
            await self._enqueue_setup_actions(
                session,
                agent_session=agent_session,
                workspace_items=workspace_items,
                message=message,
                inference_profile=inference_profile,
                user_id=user_id,
                client_request_id=client_request_id,
            )
            input_buffer = await self._enqueue_user_message(
                session,
                agent_session=agent_session,
                message=message,
                inference_profile=inference_profile,
                user_id=user_id,
                client_request_id=client_request_id,
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                agent_session.id,
            )
            if create_request is not None:
                await self.agent_session_create_request_repository.complete(
                    session,
                    request_id=create_request.id,
                    agent_session_id=agent_session.id,
                    input_buffer_id=input_buffer.id,
                    input_buffer_snapshot=input_buffer.model_dump(mode="json"),
                    completed_at=datetime.datetime.now(datetime.UTC),
                )

        return Success(
            CreatedAgentSessionInputResult(
                agent_runtime_id=runtime.id,
                agent_session=agent_session,
                input_buffer=input_buffer,
                input_buffer_pending=True,
            )
        )

    async def _load_created_session_request_result(
        self,
        session: AsyncSession,
        *,
        create_request: AgentSessionCreateRequestRecord,
    ) -> CreatedAgentSessionRequestResources | None:
        """Load a committed create result, falling back to its input snapshot."""
        session_id = create_request.agent_session_id
        input_buffer_id = create_request.input_buffer_id
        snapshot = create_request.input_buffer_snapshot
        if session_id is None or input_buffer_id is None or snapshot is None:
            return None
        agent_session = await self.agent_session_repository.lock_by_id(
            session,
            session_id,
        )
        if agent_session is None:
            return None
        input_buffer = await self.input_buffer_repository.get_by_id(
            session,
            input_buffer_id,
        )
        input_buffer_pending = input_buffer is not None
        if input_buffer is None:
            input_buffer = InputBuffer.model_validate(snapshot)
        if (
            input_buffer.id != input_buffer_id
            or input_buffer.session_id != agent_session.id
        ):
            raise RuntimeError("AgentSession create request input snapshot is invalid")
        return CreatedAgentSessionRequestResources(
            agent_session=agent_session,
            input_buffer=input_buffer,
            input_buffer_pending=input_buffer_pending,
        )

    async def _enqueue_setup_actions(
        self,
        session: AsyncSession,
        *,
        agent_session: AgentSession,
        workspace_items: list[NewSessionWorkspaceItem],
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
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
                            requested_model_target_label=inference_profile.model_target_label,
                            requested_reasoning_effort=inference_profile.reasoning_effort,
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
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        client_request_id: str | None,
    ) -> InputBuffer:
        """Enqueue one user message for an already selected AgentSession."""
        result = await self.input_buffer_service.enqueue(
            session,
            InputBufferEnqueue(
                session_id=agent_session.id,
                kind=InputBufferKind.USER_MESSAGE,
                requested_model_target_label=inference_profile.model_target_label,
                requested_reasoning_effort=inference_profile.reasoning_effort,
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


def _new_session_semantic_payload_hash(
    *,
    message: InputMessage,
    inference_profile: RequestedInferenceProfile,
    workspace_items: list[NewSessionWorkspaceItem],
) -> str:
    """Hash only client-controlled semantics for a new Session request."""
    existing_project_paths: list[str] = []
    setup_actions: list[dict[str, str]] = []
    for item in workspace_items:
        match item:
            case ExistingProjectWorkspaceItem(path=path):
                existing_project_paths.append(path)
            case GitWorktreeWorkspaceItem(
                source_project_path=source_project_path,
                starting_ref=starting_ref,
            ):
                setup_actions.append(
                    {
                        "type": "create_git_worktree",
                        "source_project_path": source_project_path,
                        "starting_ref": starting_ref,
                    }
                )
            case _:
                assert_never(item)
    payload = {
        "version": 1,
        "message": message.text,
        "attachments": message.attachments,
        "inference_profile": inference_profile.model_dump(mode="json"),
        "existing_project_paths": existing_project_paths,
        "setup_actions": setup_actions,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _existing_session_input_semantic_payload(
    *,
    kind: InputBufferKind,
    action: dict[str, JSONValue] | None,
    message: InputMessage,
    inference_profile: RequestedInferenceProfile,
) -> dict[str, object]:
    """Build the stable client-controlled semantics for an existing input."""
    return {
        "version": 1,
        "kind": kind.value,
        "message": message.text,
        "attachments": message.attachments,
        "file_parts": [
            part.model_dump(mode="json", exclude_none=True)
            for part in message.file_parts
        ],
        "inference_profile": inference_profile.model_dump(mode="json"),
        "action": action,
    }


def _matches_existing_session_input_request(
    record: ChatWriteRequest,
    *,
    payload: dict[str, object],
) -> bool:
    """Return whether a durable request represents the same input semantics."""
    return (
        record.write_type is ChatWriteRequestType.INPUT_BUFFER
        and record.accepted_type is ChatWriteRequestType.INPUT_BUFFER
        and record.history_reload_required is False
        and record.payload == payload
    )


def _reconstruct_accepted_input_buffer(
    record: ChatWriteRequest,
    *,
    kind: InputBufferKind,
    action: dict[str, JSONValue] | None,
    message: InputMessage,
    inference_profile: RequestedInferenceProfile,
) -> InputBuffer:
    """Recover the accepted identity after the pending buffer was consumed."""
    return InputBuffer(
        id=record.accepted_id,
        session_id=record.session_id,
        kind=kind,
        requested_model_target_label=inference_profile.model_target_label,
        requested_reasoning_effort=inference_profile.reasoning_effort,
        actor_user_id=record.user_id,
        content=message.text,
        idempotency_key=record.client_request_id,
        metadata=message.metadata,
        action=action,
        attachments=message.attachments,
        file_parts=message.file_parts,
        created_at=record.created_at,
    )


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
