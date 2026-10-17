"""Bind exact personal source admission to Engine effects without ambient User state."""

import dataclasses

from azents.core.engine_tool_state import McpToolSnapshotState
from azents.core.personal_toolkit_runtime import (
    PersonalToolkitExecutionDenied,
    PersonalToolkitExecutionTarget,
    ToolkitEffectAdmission,
)
from azents.engine.run.types import FunctionToolError
from azents.repos.toolkit.personal_runtime import PersonalToolkitRuntimeRepository
from azents.repos.toolkit_state.engine import McpToolSnapshotStore


@dataclasses.dataclass(frozen=True)
class PersonalToolkitAdmission:
    """A prepared source's current database admission capability."""

    repository: PersonalToolkitRuntimeRepository
    target: PersonalToolkitExecutionTarget

    async def assert_current(self) -> None:
        """Admit only this exact source; expose no owner or credential in errors."""
        try:
            await self.repository.admit(self.target)
        except PersonalToolkitExecutionDenied as error:
            raise _unavailable(error) from None


def _unavailable(error: PersonalToolkitExecutionDenied) -> FunctionToolError:
    return FunctionToolError(
        "Personal Toolkit authorization is unavailable. Reload or reconnect.",
        metadata={
            "kind": "personal_toolkit_authorization_unavailable",
            "reason": error.reason.value,
        },
    )


async def publish_tool_snapshot(
    *,
    store: McpToolSnapshotStore | None,
    snapshot: McpToolSnapshotState,
    admission: ToolkitEffectAdmission | None,
) -> None:
    """Recheck after discovery and atomically publish only the exact personal source."""
    if admission is not None:
        await admission.assert_current()
    if store is None:
        return
    if admission is None:
        await store.replace(snapshot)
        return
    if not isinstance(admission, PersonalToolkitAdmission):
        raise TypeError("Personal snapshot publication requires repository admission")
    try:
        await store.replace_personal(
            snapshot, repository=admission.repository, target=admission.target
        )
    except PersonalToolkitExecutionDenied as error:
        raise _unavailable(error) from None
