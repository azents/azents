"""Canonical Session model-profile repository results."""

import dataclasses

from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.repos.chat_write_request.data import ChatWriteRequest


@dataclasses.dataclass(frozen=True)
class WebSessionModelProfileReplacement:
    """Authorized idempotent web model-profile replacement."""

    session_id: str
    record: ChatWriteRequest
    created: bool
    model_target_label: str
    reasoning_effort: ModelReasoningEffort | None
    enabled_execution_options: list[ModelExecutionOptionId]
