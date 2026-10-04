"""Repository-owned canonical Session model-profile operations."""

from typing import Annotated

from fastapi import Depends
from pydantic import TypeAdapter

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.rdb.deps import get_session_manager
from azents.rdb.models.chat_write_request import ChatWriteRequestType
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.active_profile_admission import (
    ActiveProfileAdmissionRepository,
    ActiveProfileCaptureRequired,
    CapturedProfileAdmission,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.chat_write_request.data import (
    ChatWriteRequest,
    ChatWriteRequestCreate,
)
from azents.repos.workspace_user import WorkspaceUserRepository

from .data import WebSessionModelProfileReplacement

_EXECUTION_OPTIONS_ADAPTER = TypeAdapter(list[ModelExecutionOptionId])


class SessionModelProfileRepository:
    """Own canonical model-profile validation, idempotency, and transactions."""

    def __init__(
        self,
        agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
        agent_session_repository: Annotated[
            AgentSessionRepository, Depends(AgentSessionRepository)
        ],
        workspace_user_repository: Annotated[
            WorkspaceUserRepository, Depends(WorkspaceUserRepository)
        ],
        chat_write_request_repository: Annotated[
            ChatWriteRequestRepository, Depends(ChatWriteRequestRepository)
        ],
        active_profile_repository: Annotated[
            ActiveProfileAdmissionRepository, Depends(ActiveProfileAdmissionRepository)
        ],
        session_manager: Annotated[
            SessionManager[WriteSession], Depends(get_session_manager)
        ],
    ) -> None:
        self.agent_repository = agent_repository
        self.agent_session_repository = agent_session_repository
        self.workspace_user_repository = workspace_user_repository
        self.chat_write_request_repository = chat_write_request_repository
        self.session_manager = session_manager
        self.active_profile_repository = active_profile_repository

    async def replace_web_profile(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        profile: RequestedInferenceProfile,
        payload: dict[str, object],
    ) -> WebSessionModelProfileReplacement:
        """Preserve the public web replacement and idempotent replay contract."""
        captured_admission: CapturedProfileAdmission | None = None
        for _phase in range(2):
            try:
                write_request_repository = self.chat_write_request_repository
                profiles = self.agent_session_repository
                async with self.session_manager() as session:
                    locked = await self.lock_writable_root(
                        session,
                        agent_id=agent_id,
                        session_id=session_id,
                        user_id=user_id,
                        nowait=False,
                    )
                    existing = await write_request_repository.get_by_client_request_id(
                        session,
                        session_id=session_id,
                        requester_user_id=user_id,
                        client_request_id=client_request_id,
                    )
                    if existing is not None:
                        self._validate_record(
                            record_type=existing.write_type,
                            record_payload=existing.payload,
                            payload=payload,
                        )
                        return self._replacement_from_record(existing, created=False)

                    agent = await self.agent_repository.lock_by_id(session, agent_id)
                    if (
                        agent is None
                        or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
                        or agent.workspace_id != locked.workspace_id
                    ):
                        raise ValueError("AgentSession is not active")
                    await self.active_profile_repository.validate_in_session(
                        session,
                        agent=agent,
                        profile=profile,
                        captured=captured_admission,
                    )
                    (
                        record,
                        created,
                    ) = await self.chat_write_request_repository.create_idempotent(
                        session,
                        ChatWriteRequestCreate(
                            session_id=session_id,
                            requester_user_id=user_id,
                            creation_agent_id=None,
                            client_request_id=client_request_id,
                            write_type=ChatWriteRequestType.MODEL_PROFILE,
                            accepted_type=ChatWriteRequestType.MODEL_PROFILE,
                            accepted_id=session_id,
                            history_reload_required=False,
                            payload=payload,
                        ),
                    )
                    self._validate_record(
                        record_type=record.write_type,
                        record_payload=record.payload,
                        payload=payload,
                    )
                    if record.session_id != session_id:
                        raise ValueError(
                            "Client request ID already used for another session"
                        )
                    if created:
                        updated = await profiles.set_applied_inference_profile(
                            session,
                            session_id=session_id,
                            model_target_label=profile.model_target_label,
                            reasoning_effort=profile.reasoning_effort,
                            enabled_execution_options=profile.enabled_execution_options,
                        )
                        if updated.id != locked.id:
                            raise RuntimeError(
                                "AgentSession model profile target changed"
                            )
                    return self._replacement_from_record(record, created=created)
            except ActiveProfileCaptureRequired as needed:
                captured_admission = await self.active_profile_repository.capture(
                    needed.choice
                )
        raise ValueError("Model metadata changed before input admission")

    async def lock_writable_root(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        nowait: bool,
    ) -> AgentSession:
        """Lock and validate the exact web-writable root Session authority."""
        locked = (
            await self.agent_session_repository.lock_by_id_nowait(
                session,
                session_id,
            )
            if nowait
            else await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
        )
        if locked is None:
            raise ValueError("AgentSession not found")
        if locked.agent_id != agent_id:
            raise ValueError("AgentSession does not belong to the agent")
        if locked.session_kind is AgentSessionKind.SUBAGENT:
            raise ValueError("Subagent sessions are read-only")
        if locked.status is not AgentSessionStatus.ACTIVE:
            raise ValueError("AgentSession is not active")
        if (
            locked.product_mode is AgentSessionProductMode.USER
            and locked.associated_user_id != user_id
        ):
            raise ValueError("Requester does not have session access")
        agent = (
            await self.agent_repository.lock_by_id_nowait(
                session,
                agent_id,
            )
            if nowait
            else await self.agent_repository.lock_by_id(
                session,
                agent_id,
            )
        )
        if (
            agent is None
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.workspace_id != locked.workspace_id
        ):
            raise ValueError("AgentSession is not active")
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            session_id,
        )
        if root is None or root.agent_session_id != locked.id:
            raise ValueError("AgentSession root lineage is invalid")
        membership = await self.workspace_user_repository.get_by_workspace_and_user(
            session, workspace_id=locked.workspace_id, user_id=user_id
        )
        if membership is None:
            raise ValueError("Requester does not have session access")
        return locked

    async def get_readable_root(
        self,
        session: ReadSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> AgentSession:
        """Validate the exact readable active root Session authority."""
        readable = await self.agent_session_repository.get_by_id(session, session_id)
        if readable is None:
            raise ValueError("AgentSession not found")
        if readable.agent_id != agent_id:
            raise ValueError("AgentSession does not belong to the agent")
        if (
            readable.session_kind is not AgentSessionKind.ROOT
            or readable.status is not AgentSessionStatus.ACTIVE
        ):
            raise ValueError("AgentSession is not an active root")
        if (
            readable.product_mode is AgentSessionProductMode.USER
            and readable.associated_user_id != user_id
        ):
            raise ValueError("Requester does not have session access")
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if (
            agent is None
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.workspace_id != readable.workspace_id
        ):
            raise ValueError("AgentSession is not active")
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            session_id,
        )
        if root is None or root.agent_session_id != readable.id:
            raise ValueError("AgentSession root lineage is invalid")
        membership = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=readable.workspace_id,
            user_id=user_id,
        )
        if membership is None:
            raise ValueError("Requester does not have session access")
        return readable

    @staticmethod
    def _validate_record(
        *,
        record_type: ChatWriteRequestType,
        record_payload: dict[str, object],
        payload: dict[str, object],
    ) -> None:
        if record_type is not ChatWriteRequestType.MODEL_PROFILE:
            raise ValueError("Client request ID already used for another write type")
        if record_payload != payload:
            raise ValueError("Client request ID already used for another payload")

    @staticmethod
    def _replacement_from_record(
        record: ChatWriteRequest,
        *,
        created: bool,
    ) -> WebSessionModelProfileReplacement:
        label = record.payload.get("model_target_label")
        effort = record.payload.get("reasoning_effort")
        if not isinstance(label, str):
            raise RuntimeError("Stored model-profile payload is invalid")
        return WebSessionModelProfileReplacement(
            session_id=record.session_id,
            record=record,
            created=created,
            model_target_label=label,
            reasoning_effort=(
                ModelReasoningEffort(effort) if isinstance(effort, str) else None
            ),
            enabled_execution_options=_EXECUTION_OPTIONS_ADAPTER.validate_python(
                record.payload.get("enabled_execution_options", [])
            ),
        )
