"""Agent-facing dynamic Git worktree Toolkit."""

import json

from pydantic import BaseModel, ConfigDict, Field

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.execution_context import get_client_tool_execution_context
from azents.engine.tooling.make_tool import make_tool
from azents.services.session_git_worktree import SessionGitWorktreeService


class DynamicWorktreeToolkitConfig(BaseModel):
    """Configuration for the always-resolved Dynamic Worktree Toolkit."""


class CreateGitWorktreeInput(BaseModel):
    """Create one Agent-managed Git worktree from a current Session Project."""

    model_config = ConfigDict(extra="forbid")

    source_project_path: str = Field(
        min_length=1,
        description="Exact current Session Project path under the Agent Workspace.",
    )
    starting_ref: str | None = Field(
        description=(
            "Optional Git ref. Omit it to use the selected Project worktree's "
            "current HEAD commit."
        ),
    )
    branch_name: str | None = Field(
        description=(
            "Optional new branch name. Omit it to generate a collision-free "
            "Session-related branch."
        ),
    )


class DynamicWorktreeToolkit(Toolkit[DynamicWorktreeToolkitConfig]):
    """Expose durable Agent-managed worktree operations when currently eligible."""

    def __init__(
        self,
        *,
        service: SessionGitWorktreeService,
        broker: SessionBroker,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Create a Session-bound Dynamic Worktree Toolkit."""
        self.service = service
        self.broker = broker
        self.agent_id = agent_id
        self.session_id = session_id
        self.run_id: str | None = None
        self.turn_action_bridge_boundary: TurnActionBridgeBoundary | None = None

    def bind_run(
        self,
        *,
        run_id: str,
        turn_action_bridge_boundary: TurnActionBridgeBoundary,
    ) -> None:
        """Bind the current Run identity and its private bridge observation latch."""
        self.run_id = run_id
        self.turn_action_bridge_boundary = turn_action_bridge_boundary

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Project creation only while current Session Runtime authority is eligible."""
        del context
        if not await self.service.agent_create_git_worktree_available(
            agent_id=self.agent_id,
            session_id=self.session_id,
        ):
            return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=[self._create_git_worktree_tool()],
        )

    def _create_git_worktree_tool(self) -> FunctionTool:
        async def create_git_worktree(input: CreateGitWorktreeInput) -> str:
            """Durably request a managed worktree from an exact current Project."""
            run_id = self.run_id
            boundary = self.turn_action_bridge_boundary
            if run_id is None or boundary is None:
                raise FunctionToolError(
                    "Dynamic worktree authority is unavailable for this Run."
                )
            execution = get_client_tool_execution_context()
            try:
                admission = await self.service.admit_agent_create_git_worktree(
                    agent_id=self.agent_id,
                    session_id=self.session_id,
                    originating_run_id=run_id,
                    client_tool_call_id=execution.call_id,
                    source_project_path=input.source_project_path,
                    starting_ref=input.starting_ref,
                    branch_name=input.branch_name,
                )
            except ValueError as error:
                raise FunctionToolError(str(error)) from None
            boundary.mark_admitted(execution.call_id)
            await self.broker.notify_mailbox_activity(self.session_id)
            await self.broker.send_message(SessionWakeUp(session_id=self.session_id))
            return json.dumps(
                {
                    "accepted": True,
                    "request_id": admission.mailbox_item_id,
                    "message": (
                        "The worktree request was accepted. The authoritative "
                        "result will arrive through a fresh continuation Run."
                    ),
                },
                sort_keys=True,
            )

        return make_tool(
            create_git_worktree,
            description=(
                "Durably request a managed Git worktree from an exact Project in "
                "the current Session context. This returns acceptance only; wait "
                "for the continuation result before using the generated path."
            ),
            input_model=CreateGitWorktreeInput,
        )


class DynamicWorktreeToolkitProvider(
    ToolkitProvider[DynamicWorktreeToolkitConfig],
):
    """Always-resolved provider for Agent-managed dynamic worktrees."""

    slug = "dynamic_worktree"
    name = "Dynamic Worktree"
    description = "Create managed Git worktrees from current Session Projects"
    system_prompt = ""
    config_model = DynamicWorktreeToolkitConfig

    def __init__(
        self,
        *,
        service: SessionGitWorktreeService,
        broker: SessionBroker,
    ) -> None:
        """Create the provider."""
        self.service = service
        self.broker = broker

    async def resolve(
        self,
        config: DynamicWorktreeToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[DynamicWorktreeToolkitConfig]:
        """Create one Session-bound Toolkit instance."""
        del config
        return DynamicWorktreeToolkit(
            service=self.service,
            broker=self.broker,
            agent_id=context.agent_id,
            session_id=context.session_id,
        )
