"""Public AgentSessionInputService facade over completed repository operations."""

import dataclasses
from typing import Annotated

from azcommon.result import Result
from fastapi import Depends

from azents.core.agent_session_input_data import (
    AgentSessionInputError,
    BufferedAgentSessionInputResult,
    CreatedAgentSessionInputResult,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
)
from azents.engine.events.action_messages import (
    CreateGitWorktreeAction,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.event import JSONValue
from azents.repos.agent_session_input_operations import (
    AgentSessionInputOperationsRepository,
)


@dataclasses.dataclass
class AgentSessionInputService:
    """Delegate atomic admission to its owning database repository."""

    operations: Annotated[
        AgentSessionInputOperationsRepository,
        Depends(AgentSessionInputOperationsRepository),
    ]

    async def create_buffered_agent_input(
        self,
        *,
        agent_id: str,
        agent_session_id: str,
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        request_payload: dict[str, object],
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Sequence one completed database operation."""
        return await self.operations.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            request_payload=request_payload,
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
        request_payload: dict[str, object],
        client_request_id: str | None = None,
    ) -> Result[BufferedAgentSessionInputResult, AgentSessionInputError]:
        """Sequence one completed database operation."""
        return await self.operations.create_buffered_agent_action_input(
            agent_id=agent_id,
            agent_session_id=agent_session_id,
            action=action,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            request_payload=request_payload,
            client_request_id=client_request_id,
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
        request_payload: dict[str, object],
        client_request_id: str | None = None,
    ) -> Result[CreatedAgentSessionInputResult, AgentSessionInputError]:
        """Sequence one completed database operation."""
        return await self.operations.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            existing_project_paths=existing_project_paths,
            setup_actions=setup_actions,
            request_payload=request_payload,
            client_request_id=client_request_id,
        )

    async def create_user_session_with_buffered_input(
        self,
        *,
        agent_id: str,
        message: InputMessage,
        inference_profile: RequestedInferenceProfile,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
        request_payload: dict[str, object],
        client_request_id: str | None = None,
    ) -> Result[CreatedAgentSessionInputResult, AgentSessionInputError]:
        """Sequence one completed database operation."""
        return await self.operations.create_user_session_with_buffered_input(
            agent_id=agent_id,
            message=message,
            inference_profile=inference_profile,
            user_id=user_id,
            existing_project_paths=existing_project_paths,
            setup_actions=setup_actions,
            request_payload=request_payload,
            client_request_id=client_request_id,
        )
