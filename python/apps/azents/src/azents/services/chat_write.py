"""Public ChatWriteService facade over completed repository operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.chat_write_data import (
    AcceptedEditInput,
    AcceptedFailedRunRetry,
    AcceptedModelProfile,
    AcceptedPendingCommand,
    AcceptedStopRequest,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.events.types import FileOutputPart
from azents.repos.chat_write_operations import ChatWriteOperationsRepository


@dataclasses.dataclass
class ChatWriteService:
    """Delegate atomic admission to its owning database repository."""

    operations: Annotated[
        ChatWriteOperationsRepository, Depends(ChatWriteOperationsRepository)
    ]

    async def create_idempotent_edit_input(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        message_id: str,
        text: str,
        inference_profile: RequestedInferenceProfile,
        metadata: dict[str, str],
        attachments: list[str],
        file_parts: list[FileOutputPart],
        payload: dict[str, object],
    ) -> AcceptedEditInput:
        """Sequence one completed database operation."""
        return await self.operations.create_idempotent_edit_input(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id=client_request_id,
            message_id=message_id,
            text=text,
            inference_profile=inference_profile,
            metadata=metadata,
            attachments=attachments,
            file_parts=file_parts,
            payload=payload,
        )

    async def create_idempotent_pending_command(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        command_name: str,
        payload: dict[str, object],
    ) -> AcceptedPendingCommand:
        """Sequence one completed database operation."""
        return await self.operations.create_idempotent_pending_command(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id=client_request_id,
            command_name=command_name,
            payload=payload,
        )

    async def create_idempotent_failed_run_retry(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        failed_event_id: str,
        payload: dict[str, object],
    ) -> AcceptedFailedRunRetry:
        """Sequence one completed database operation."""
        return await self.operations.create_idempotent_failed_run_retry(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id=client_request_id,
            failed_event_id=failed_event_id,
            payload=payload,
        )

    async def request_session_stop(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> AcceptedStopRequest:
        """Sequence one completed database operation."""
        return await self.operations.request_session_stop(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def replace_session_model_profile(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
        model_target_label: str,
        reasoning_effort: ModelReasoningEffort | None,
        enabled_execution_options: list[ModelExecutionOptionId],
        payload: dict[str, object],
    ) -> AcceptedModelProfile:
        """Sequence one completed database operation."""
        return await self.operations.replace_session_model_profile(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            client_request_id=client_request_id,
            model_target_label=model_target_label,
            reasoning_effort=reasoning_effort,
            enabled_execution_options=enabled_execution_options,
            payload=payload,
        )
