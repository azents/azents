"""Background task result injection."""

import asyncio
import dataclasses
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import InputBufferKind
from azents.engine.run.background import BackgroundTask
from azents.engine.run.types import FunctionToolResult
from azents.rdb.session import SessionManager
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService

logger = logging.getLogger(__name__)


def _function_tool_result_text(result: FunctionToolResult) -> str:
    """Summarize FunctionToolResult output as background completion text."""
    if isinstance(result.output, str):
        return result.output
    parts: list[str] = []
    for item in result.output:
        type_value = item["type"] if "type" in item else "output"
        if type_value in {"text", "output_text"}:
            text = item["text"] if "text" in item else ""
            if isinstance(text, str) and text:
                parts.append(text)
                continue
        label = str(type_value)
        name = item["name"] if "name" in item else None
        uri = item["uri"] if "uri" in item else None
        if isinstance(name, str) and name:
            parts.append(f"[{label}: {name}]")
            continue
        if isinstance(uri, str) and uri:
            parts.append(f"[{label}: {uri}]")
            continue
        parts.append(f"[{label}]")
    return "\n".join(parts)


@dataclasses.dataclass(frozen=True)
class BackgroundTaskResultInjector:
    """Inject Background task completion result into parent session input buffer."""

    broker: SessionBroker
    session_manager: SessionManager[AsyncSession]
    input_buffer_service: InputBufferService

    async def inject(self, task: BackgroundTask) -> None:
        """Inject Background task completion as new parent session InputBuffer.

        Build text from Task future result (or exception),
        then trigger new run via broker wake-up after input buffer commit.

        :param task: Completed background task entry
        """
        if task.future.cancelled():
            logger.info(
                "Background task was cancelled; skipping result injection",
                extra={
                    "task_id": task.task_id,
                    "tool_name": task.tool_name,
                    "parent_session_id": task.parent_session_id,
                },
            )
            return

        try:
            exc = task.future.exception()
        except asyncio.CancelledError:
            logger.info(
                "Background task was cancelled; skipping result injection",
                extra={
                    "task_id": task.task_id,
                    "tool_name": task.tool_name,
                    "parent_session_id": task.parent_session_id,
                },
            )
            return

        if exc is not None:
            logger.exception(
                "Background task failed",
                extra={
                    "task_id": task.task_id,
                    "tool_name": task.tool_name,
                    "parent_session_id": task.parent_session_id,
                },
                exc_info=exc,
            )
            text = (
                f"[Background task '{task.tool_name}' failed]\n"
                f"Task ID: {task.task_id}\n"
                f"Error: An unexpected error occurred during background execution."
            )
        else:
            result = task.future.result()
            if isinstance(result, FunctionToolResult):
                content = _function_tool_result_text(result)
            else:
                content = str(result)
            text = (
                f"[Background task '{task.tool_name}' completed]\n"
                f"Task ID: {task.task_id}\n\n"
                f"{content}"
            )

        try:
            async with self.session_manager() as session:
                await self.input_buffer_service.enqueue(
                    session,
                    InputBufferEnqueue(
                        session_id=task.parent_session_id,
                        kind=InputBufferKind.BACKGROUND_COMPLETION,
                        actor_user_id=None,
                        content=text,
                        idempotency_key=f"background-task:{task.task_id}",
                        metadata={
                            "source": "background_task",
                            "task_id": task.task_id,
                            "tool_name": task.tool_name,
                        },
                        attachments=[],
                        file_parts=[],
                    ),
                )

            await self.broker.send_message(
                SessionWakeUp(
                    agent_id=task.agent_id,
                    session_id=task.parent_session_id,
                    user_id=None,
                    additional_system_prompt=None,
                    interface=None,
                    workspace_id=task.workspace_id,
                    workspace_handle=None,
                )
            )
            logger.info(
                "Background task result injected into parent session",
                extra={
                    "task_id": task.task_id,
                    "tool_name": task.tool_name,
                    "parent_session_id": task.parent_session_id,
                },
            )
        except Exception:
            logger.exception(
                "Failed to inject background task result",
                extra={
                    "task_id": task.task_id,
                    "parent_session_id": task.parent_session_id,
                },
            )
