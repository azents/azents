"""Session-scoped todo Toolkit State tools."""

from collections.abc import Awaitable, Callable
from typing import Literal, Self, assert_never

from pydantic import BaseModel, Field

from azents.core.engine_tool_state import (
    TODO_STATE_SCHEMA_VERSION,
    TodoItem,
    TodoState,
    TodoStatus,
)
from azents.core.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_owner,
)
from azents.core.toolkit_state import ToolkitStateModel
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.events.engine_events import TodoStateChanged
from azents.engine.hooks.types import (
    CompactionSummaryHookContext,
    CompactionSummaryReplace,
    RuntimeHooks,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.repos.toolkit_state.engine import TodoStateStore

TODO_STATUS_VALUES = {"pending", "in_progress", "completed"}
TodoOperation = Literal["replace", "clear"]

_TODO_PROMPT = """### Todo List

Use `update_todo` to maintain a session-scoped todo list whenever the work has
multiple steps or the user asks for progress tracking. The todo list is shown to
the user in the chat UI.

- Store only actionable tasks.
- Use `replace` with the full current list when changing todo items.
- Use `clear` when there is no active todo list.
- Use status values exactly as defined: `pending`, `in_progress`, `completed`.
- Keep todo items ordered by execution priority; put the next item to work on first.
- Keep at most one item `in_progress` unless the user explicitly asks for parallel work.
- Update the todo list as work progresses.
"""


class TodoUpdateItem(BaseModel):
    """update_todo tool input item."""

    content: str = Field(min_length=1, max_length=500, description="Todo text")
    status: TodoStatus = Field(description="Todo status")


class UpdateTodoInput(ToolkitStateModel):
    """update_todo tool input."""

    schema_version: int = TODO_STATE_SCHEMA_VERSION
    operation: TodoOperation = Field(description="Update operation: replace or clear")
    items: list[TodoUpdateItem] = Field(
        default_factory=list,
        description="Full todo list for replace operations",
    )


class TodoToolkitConfig(BaseModel):
    """Todo Toolkit settings model."""


class TodoToolkit(Toolkit[TodoToolkitConfig]):
    """Always-on Toolkit that manages session todo state."""

    def __init__(
        self,
        *,
        store: TodoStateStore,
        agent_id: str = "",
        session_id: str = "",
    ) -> None:
        """Create Todo Toolkit."""
        self.store = store
        self._agent_id = agent_id
        self._session_id = session_id
        self._execution_owner: SessionExecutionOwner | None = None

    def bind_execution_owner(
        self,
        owner: SessionExecutionOwner,
    ) -> None:
        """Bind this resolved Toolkit to one immutable Session owner."""
        if accepts_execution_owner(
            self._execution_owner,
            owner,
            session_id=self._session_id,
        ):
            self._execution_owner = owner

    def bind_execution_authority(
        self,
        authority: SessionResourceAuthority,
    ) -> None:
        """Validate full resource identity and bind its durable owner."""
        if authority.agent_id != self._agent_id:
            raise ValueError("Execution authority Agent does not match Toolkit")
        self.bind_execution_owner(authority.execution_owner)

    def set_agent_id(self, agent_id: str) -> None:
        """Inject agent_id."""
        self._agent_id = agent_id

    def set_session_id(self, session_id: str) -> None:
        """Inject session_id."""
        self._session_id = session_id

    def hooks(self) -> RuntimeHooks:
        """Return Todo lifecycle hooks."""
        return {"on_compaction_summary": self._on_compaction_summary}

    async def _on_compaction_summary(
        self,
        context: CompactionSummaryHookContext,
    ) -> CompactionSummaryReplace | None:
        """Append current Todo state to compaction summary."""
        if not self._agent_id or not self._session_id:
            return None
        state = await self.store.load(self._agent_id, self._session_id)
        snapshot = render_todo_snapshot(state)
        if snapshot is None:
            return None
        return CompactionSummaryReplace(
            summary=f"{context.summary.rstrip()}\n\n{snapshot}"
        )

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return current todo prompt and update_todo tool."""
        if context.resource_authority is not None:
            self.bind_execution_authority(context.resource_authority)
        if not self._session_id:
            return ToolkitState(
                status=ToolkitStatus.ENABLED,
                tools=[],
            )

        async def publish_todo_changed(snapshot: TodoStateSnapshot) -> None:
            await context.publish_event(
                TodoStateChanged(todo=snapshot.model_dump(mode="json"))
            )

        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[
                make_update_todo_tool(
                    store=self.store,
                    agent_id=self._agent_id,
                    session_id=self._session_id,
                    publish_changed=publish_todo_changed,
                )
            ],
        )


class TodoToolkitProvider(ToolkitProvider[TodoToolkitConfig]):
    """Todo Toolkit provider always injected without user settings."""

    slug = "todo"
    name = "Todo"
    description = "Maintain the session todo list"
    system_prompt = ""
    config_model = TodoToolkitConfig

    def __init__(self, *, store: TodoStateStore) -> None:
        """Create Todo Toolkit provider."""
        self.store = store

    async def resolve(
        self,
        config: TodoToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[TodoToolkitConfig]:
        """Return executable Todo Toolkit."""
        return TodoToolkit(store=self.store)


def render_todo_prompt(state: TodoState | None = None) -> str:
    """Render stable prompt fragment for todo tools."""
    del state
    return _TODO_PROMPT


def render_todo_snapshot(state: TodoState) -> str | None:
    """Render Todo state for compaction summary enrichment."""
    if not state.items:
        return None
    lines = ["## Todo Snapshot", "", "Session Todo state at compaction time:"]
    lines.extend(f"- [{item.status}] {item.content}" for item in state.items)
    return "\n".join(lines)


def make_update_todo_tool(
    *,
    store: TodoStateStore,
    agent_id: str,
    session_id: str,
    publish_changed: Callable[[TodoStateSnapshot], Awaitable[None]] | None = None,
) -> FunctionTool:
    """Create update_todo FunctionTool."""

    async def update_todo(args: UpdateTodoInput) -> str:
        """Update the session todo list shown in the chat UI."""
        if not session_id:
            raise FunctionToolError("Session ID is not available.")
        updated = await store.replace(
            agent_id,
            session_id,
            apply_todo_update(TodoState(), args),
        )
        snapshot = TodoStateSnapshot.from_state(updated)
        if publish_changed is not None:
            await publish_changed(snapshot)
        return "Done"

    return make_tool(update_todo, input_model=UpdateTodoInput)


def apply_todo_update(_current: TodoState, update: UpdateTodoInput) -> TodoState:
    """Apply update_todo input to todo state."""
    match update.operation:
        case "clear":
            return TodoState()
        case "replace":
            return TodoState(items=[_to_item(item) for item in update.items])
        case _ as unreachable:
            assert_never(unreachable)


def _to_item(item: TodoUpdateItem) -> TodoItem:
    """Convert tool input item to stored item."""
    return TodoItem(content=item.content, status=item.status)


class TodoItemSnapshot(BaseModel):
    """Todo item exposed to Chat live snapshot."""

    content: str
    status: TodoStatus

    @classmethod
    def from_item(cls, item: TodoItem) -> Self:
        """Create snapshot item from stored item."""
        return cls(content=item.content, status=item.status)


class TodoStateSnapshot(ToolkitStateModel):
    """Todo state exposed to Chat live snapshot."""

    schema_version: int = TODO_STATE_SCHEMA_VERSION
    items: list[TodoItemSnapshot] = Field(default_factory=list)

    @classmethod
    def from_state(cls, state: TodoState) -> Self:
        """Create snapshot from stored state."""
        return cls(items=[TodoItemSnapshot.from_item(item) for item in state.items])
