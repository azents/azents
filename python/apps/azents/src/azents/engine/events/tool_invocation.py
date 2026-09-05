"""Internal pre-cap client Tool invocation contracts."""

from dataclasses import dataclass
from typing import Literal, Protocol

from azcommon.types import JSONObject

from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.generated_files import PendingGeneratedFileOutput
from azents.engine.events.output_parts import enforce_tool_output_text_hard_cap
from azents.engine.events.types import ClientToolResultPayload, ToolOutput


@dataclass(frozen=True)
class PreparedClientToolInvocation:
    """Client Tool invocation independent from durable native artifacts."""

    call_id: str
    name: str
    arguments: str
    wire_dialect: ClientToolWireDialect


@dataclass(frozen=True)
class UnboundedClientToolResult:
    """Normalized Tool result before model-visible text capping."""

    call_id: str
    name: str
    wire_dialect: ClientToolWireDialect
    status: Literal["completed", "failed"]
    execution_succeeded: bool
    output: ToolOutput
    metadata: JSONObject
    pending_generated_files: tuple[PendingGeneratedFileOutput, ...]
    terminal_run: bool

    def to_client_tool_result(self) -> ClientToolResultPayload:
        """Apply the ordinary Tool output cap and build the durable payload."""
        return ClientToolResultPayload(
            call_id=self.call_id,
            name=self.name,
            wire_dialect=self.wire_dialect,
            status=self.status,
            output=enforce_tool_output_text_hard_cap(self.output),
            metadata=dict(self.metadata),
            pending_generated_files=list(self.pending_generated_files),
            terminal_run=self.terminal_run,
        )


class ClientToolInvoker(Protocol):
    """Execute prepared client Tools before model-result capping."""

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        """Invoke one prepared client Tool."""
        ...

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """Request cancellation for one active invocation."""
        ...
