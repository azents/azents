"""Subagent tool.

Create a single tool that lets parent agent call subagent.
Integrates all subagents into one `subagent` tool,
and selects target subagent with `agent` parameter.
"""

import asyncio
import dataclasses
import json
import logging
import time
from collections.abc import Awaitable, Callable
from textwrap import dedent
from typing import Any

from azcommon.result import Failure
from azcommon.uuid import uuid7
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker
from azents.core.tools import (
    SessionType,
    SubagentToolkitContext,
    ToolkitContext,
    ToolkitProvider,
)
from azents.engine.events.builders import (
    make_subagent_end_event,
    make_subagent_start_event,
)
from azents.engine.events.types import Event
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.contracts import AgentEngineProtocol, RunContext
from azents.engine.run.emit import (
    PublishedEvent,
    collect_event_result,
    handle_engine_event,
)
from azents.engine.run.input import InputMessage, InvokeInput
from azents.engine.run.resolve import (
    resolve_agent_tools,
    resolve_invoke_input_with_model_source,
)
from azents.engine.run.types import (
    CheckStop,
    FunctionTool,
    FunctionToolError,
    ShutdownInterruptError,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.goal import GoalToolkitProvider
from azents.engine.tools.skill import SkillToolkitProvider
from azents.engine.tools.todo import TodoToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_subagent.data import AgentSubagent, SubagentToolkitInheritMode
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.runtime.types import RuntimeDomainConfig
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService

logger = logging.getLogger(__name__)

# Subagent tool name constants
SUBAGENT_TOOL_NAME = "subagent"

# System prompt suffix injected into Subagent
_SUBAGENT_SYSTEM_PROMPT_SUFFIX = dedent("""\


## Important Instructions

- Act autonomously. Make your best judgment and provide a complete answer directly.
""")  # noqa: E501


def resolve_toolkit_source_agent_id(
    toolkit_inherit_mode: SubagentToolkitInheritMode,
    parent_agent_id: str,
    subagent_id: str,
) -> str:
    """Decide which agent to load toolkit from on Subagent call.

    Toolkit inherit rule (DP6 — exclusive):

    - When ``mode=ALL``, use only parent own toolkit and completely ignore subagent
      ``agent_toolkits``.
    - When ``mode=NONE``, use subagent own toolkit (existing behavior).

    :param toolkit_inherit_mode: inherit mode of subagent agent row (DP1 A)
    :param parent_agent_id: Parent agent id
    :param subagent_id: Subagent id
    :return: agent_id passed to ``resolve_agent_tools``
    """
    if toolkit_inherit_mode == SubagentToolkitInheritMode.ALL:
        return parent_agent_id
    return subagent_id


@dataclasses.dataclass(frozen=True)
class SubagentToolContext:
    """Dependency context needed to create Subagent tool.

    :param engine: AgentEngine instance
    :param parent_session_id: Parent session ID
    :param parent_agent_id: Parent agent ID for runtime tool context sharing
    :param workspace_id: Workspace ID
    :param user_id: User ID
    :param agent_repository: Agent repository
    :param integration_repository: LLM integration repository
    :param exchange_file_service: Exchange URI attachment resolution service
    :param model_file_service: ModelFile creation service
    :param session_manager: DB session manager
    :param toolkit_registry: tool_slug -> ToolkitProvider mapping
    :param agent_toolkit_repository: AgentToolkit repository
    :param toolkit_repository: Toolkit repository
    :param agent_runtime_repository: AgentRuntime repository
    :param agent_session_repository: AgentSession repository
    :param publish_event: Engine event publish callback
    :param web_url: Frontend URL for OAuth redirect_uri construction
    :param oauth_secret_key: OAuth HMAC signing key
    :param parent_runtime_domain_config: parent runtime domain settings
        injected into subagent
    :param shutdown_event: Worker shutdown event; no shutdown detection when None
    """

    engine: AgentEngineProtocol
    parent_session_id: str
    parent_agent_id: str
    parent_runtime_domain_config: RuntimeDomainConfig
    workspace_id: str
    user_id: str | None
    agent_repository: AgentRepository
    integration_repository: LLMProviderIntegrationRepository
    exchange_file_service: ExchangeFileService
    model_file_service: ModelFileService
    session_manager: SessionManager[AsyncSession]
    toolkit_registry: dict[str, ToolkitProvider[Any]]
    agent_toolkit_repository: AgentToolkitRepository
    toolkit_repository: ToolkitRepository
    agent_runtime_repository: AgentRuntimeRepository
    agent_session_repository: AgentSessionRepository
    publish_event: Callable[[PublishedEvent], Awaitable[None]]
    broker: SessionBroker
    builtin_toolkit_provider: BuiltinToolkitProvider | None
    todo_toolkit_provider: TodoToolkitProvider | None
    goal_toolkit_provider: GoalToolkitProvider | None
    skill_toolkit_provider: SkillToolkitProvider | None
    web_url: str
    oauth_secret_key: str
    mcp_proxy_url: str | None
    session_type: SessionType
    parent_run_id: str | None = None
    parent_check_stop: CheckStop | None = None
    shutdown_event: asyncio.Event | None = None


async def _append_parent_event(
    ctx: SubagentToolContext,
    event: Event,
) -> Event:
    """Append event to parent transcript and return append result."""
    async with ctx.session_manager() as db_session:
        appended = await EventTranscriptRepository().append(
            db_session,
            EventCreate(
                session_id=ctx.parent_session_id,
                kind=event.kind,
                payload=event.payload.model_dump(mode="json", exclude_none=True),
            ),
        )
        await db_session.commit()
        return appended


def _build_description(
    subagents: list[tuple[AgentSubagent, str]],
) -> str:
    """Create description for unified subagent tool.

    Combine common description and per-subagent description into one string.

    :param subagents: List of (AgentSubagent, subagent_name) tuples
    :return: Unified description string
    """
    header = dedent("""\
        Delegate a task to a specialized subagent.
        The subagent will execute the task autonomously and return the result to you (the caller), not directly to the user.
        Use the result to formulate your response.

        The subagent has no conversation context — provide a comprehensive, self-contained task description with all necessary background and requirements.
        """)  # noqa: E501

    agent_lines: list[str] = []
    for junction, name in subagents:
        agent_lines.append(f"- **{name}**: {junction.description}")

    return header + "\n\nAvailable agents:\n" + "\n".join(agent_lines)


async def _resolve_subagent_session_id(
    *,
    ctx: SubagentToolContext,
    subagent_id: str,
    existing_session_id: str | None,
) -> str:
    """Decide session ID to use for Subagent call.

    If ``session_id`` is given and actual row exists, reuse it as-is. Otherwise,
    use the target subagent's team primary session.

    :param ctx: Subagent tool dependency context
    :param subagent_id: Target subagent Agent ID
    :param existing_session_id: Existing session ID requested for reuse
    :return: Subagent session ID to use
    """
    if existing_session_id is not None:
        async with ctx.session_manager() as db_session:
            existing = await ctx.agent_session_repository.get_by_id(
                db_session, existing_session_id
            )
        if existing is not None:
            return existing_session_id

        logger.warning(
            "Subagent session not found, rotating to a new active session",
            extra={
                "requested_session_id": existing_session_id,
                "subagent_id": subagent_id,
            },
        )

    async with ctx.session_manager() as db_session:
        runtime = await ctx.agent_runtime_repository.ensure_for_agent(
            db_session, subagent_id
        )
        agent_session = (
            await ctx.agent_session_repository.ensure_team_primary_for_agent(
                db_session,
                workspace_id=runtime.workspace_id,
                agent_id=subagent_id,
            )
        )
        await db_session.commit()
        return agent_session.id


def create_unified_subagent_tool(
    subagents: list[tuple[AgentSubagent, str]],
    ctx: SubagentToolContext,
) -> FunctionTool:
    """Create all subagents as one unified tool.

    Select target subagent with `agent` parameter and delegate task with `task`.

    :param subagents: List of (AgentSubagent, subagent_name) tuples
    :param ctx: Subagent tool dependency context
    :return: Unified subagent FunctionTool instance
    """
    # subagent name to junction mapping
    junction_by_name: dict[str, AgentSubagent] = {
        name: junction for junction, name in subagents
    }
    agent_names = list(junction_by_name.keys())

    class SubagentInput(BaseModel):
        """subagent tool input."""

        agent: str = Field(description="The subagent to delegate the task to.")
        task: str = Field(description="The task to delegate to the subagent.")
        session_id: str | None = Field(
            default=None,
            description=(
                "Optional. Existing subagent session ID to resume. "
                "If not provided, a new session is created."
            ),
        )

    # Preliminary schema for adding Agent names as enum; merged below.
    agent_enum_values = agent_names

    async def handler(input: SubagentInput) -> str:
        """Call Subagent and run task."""
        agent_name = input.agent
        task = input.task
        existing_session_id = input.session_id

        junction = junction_by_name.get(agent_name)
        if junction is None:
            raise FunctionToolError(
                f"Unknown agent: {agent_name}. "
                f"Available agents: {', '.join(agent_names)}"
            )

        subagent_id = junction.subagent_id

        session_id = await _resolve_subagent_session_id(
            ctx=ctx,
            subagent_id=subagent_id,
            existing_session_id=existing_session_id,
        )

        async with ctx.session_manager() as db_session:
            subagent = await ctx.agent_repository.get_by_id(db_session, subagent_id)

        # Subagent also has its own model snapshot. Parent model runtime
        # inheritance was removed with model selection snapshot transition.
        invoke_input = InvokeInput(
            agent_id=subagent_id,
            session_id=session_id,
            messages=[
                InputMessage(
                    text=task, user_id=None, headers=[], metadata={}, attachments=[]
                )
            ],
            user_id=ctx.user_id,
        )

        resolved = await resolve_invoke_input_with_model_source(
            invoke_input,
            model_source_agent_id=subagent_id,
            agent_repository=ctx.agent_repository,
            integration_repository=ctx.integration_repository,
            session_manager=ctx.session_manager,
            exchange_file_service=ctx.exchange_file_service,
            model_file_service=ctx.model_file_service,
        )

        if isinstance(resolved, Failure):
            raise FunctionToolError(f"Failed to resolve subagent: {resolved.error}")

        run_request = resolved.value

        # Resolve Subagent toolkit
        # Use parent_session_id as session_id so runtime and file tools both
        # share parent session storage (see design document).
        run_id = uuid7().hex
        context = ToolkitContext(
            session_id=ctx.parent_session_id,
            workspace_id=run_request.workspace_id,
            agent_id=subagent_id,
            user_id=ctx.user_id,
            run_id=run_id,
            publish_event=ctx.publish_event,
            session_type=ctx.session_type,
            interface_type=None,
            interface_channel_id=None,
        )

        # Decide Toolkit source (DP6: exclusive inherit). See helper
        # ``resolve_toolkit_source_agent_id``.
        # DP1 A: toolkit_inherit_mode is stored in agent row.
        toolkit_source_agent_id = resolve_toolkit_source_agent_id(
            toolkit_inherit_mode=(
                subagent.toolkit_inherit_mode
                if subagent is not None
                else SubagentToolkitInheritMode.NONE
            ),
            parent_agent_id=ctx.parent_agent_id,
            subagent_id=subagent_id,
        )

        async with ctx.session_manager() as db_session:
            # Shell enabled state comes from subagent own settings, not inherited.
            # If subagent shell_enabled is False, builtin_provider=None.
            builtin_provider = (
                ctx.builtin_toolkit_provider
                if subagent is not None and subagent.shell_enabled
                else None
            )

            toolkits = await resolve_agent_tools(
                toolkit_source_agent_id,
                context,
                toolkit_registry=ctx.toolkit_registry,
                agent_toolkit_repository=ctx.agent_toolkit_repository,
                toolkit_repository=ctx.toolkit_repository,
                session=db_session,
                web_url=ctx.web_url,
                oauth_secret_key=ctx.oauth_secret_key,
                mcp_proxy_url=ctx.mcp_proxy_url,
                runtime_domain_config=ctx.parent_runtime_domain_config,
                builtin_toolkit_provider=builtin_provider,
                todo_toolkit_provider=ctx.todo_toolkit_provider,
                goal_toolkit_provider=ctx.goal_toolkit_provider,
                skill_toolkit_provider=ctx.skill_toolkit_provider,
                memory_enabled=False,
            )

        # Share parent execution context; Toolkit encapsulates adjustment.
        subagent_toolkit_context = SubagentToolkitContext(
            parent_agent_id=ctx.parent_agent_id,
            parent_session_id=ctx.parent_session_id,
            subagent_id=subagent_id,
            subagent_session_id=session_id,
        )
        for binding in toolkits:
            binding.toolkit.configure_for_subagent(subagent_toolkit_context)

        run_request = dataclasses.replace(
            run_request,
            toolkits=toolkits,
        )

        # Add system prompt suffix + specify parent session for output storage.
        # Subagent outputs must be exported as parent session Exchange artifacts.
        run_request = dataclasses.replace(
            run_request,
            agent_prompt=(run_request.agent_prompt or "")
            + _SUBAGENT_SYSTEM_PROMPT_SUFFIX,
            storage_session_id=ctx.parent_session_id,
            storage_agent_id=ctx.parent_agent_id,
            storage_path_prefix=f"subagent-{session_id}/",
        )

        # Wrap check_stop: detect parent stop + parent task death
        parent_task = asyncio.current_task()

        async def subagent_check_stop() -> bool:
            if ctx.parent_check_stop is not None and await ctx.parent_check_stop():
                return True
            if parent_task is not None and parent_task.done():
                return True
            return False

        # Publish and persist subagent_start event
        subagent_start = await _append_parent_event(
            ctx,
            make_subagent_start_event(
                session_id=ctx.parent_session_id,
                subagent_run_id=run_id,
                subagent_id=subagent_id,
                subagent_name=agent_name,
                subagent_session_id=session_id,
            ),
        )
        await ctx.publish_event(subagent_start)

        # Run engine.run() and collect results
        # Persist/publish events and collect results.
        # Refresh parent session activity TTL during subagent run.
        _PARENT_REFRESH_INTERVAL = 10  # seconds
        last_parent_refresh = time.monotonic()
        result_texts: list[str] = []
        result_attachments: list[RuntimeAttachment] = []

        async def publish_to_broker(ev: PublishedEvent) -> None:
            await ctx.broker.publish_event(session_id, ev)

        subagent_run_context = RunContext(
            user_id=ctx.user_id,
            run_id=run_id,
            publish_event=publish_to_broker,
        )

        try:
            async for item in ctx.engine.run(
                run_request,
                subagent_run_context,
                check_stop=subagent_check_stop,
            ):
                await handle_engine_event(
                    item,
                    publish=publish_to_broker,
                )
                collect_event_result(item.event, result_texts, result_attachments)
                # Periodic parent session activity TTL refresh
                now = time.monotonic()
                if (
                    ctx.parent_run_id
                    and now - last_parent_refresh >= _PARENT_REFRESH_INTERVAL
                ):
                    await ctx.broker.renew_session_ttl(ctx.parent_session_id)
                    last_parent_refresh = now
        except Exception:
            logger.exception(
                "Subagent engine run failed",
                extra={
                    "subagent_id": subagent_id,
                    "session_id": session_id,
                },
            )
            result_texts.append(
                "Error: An unexpected error occurred"
                f" while running subagent '{agent_name}'."
            )

        # -- shutdown detection: outside try block to avoid except Exception --
        # When stopped by check_stop, async for exits normally and reaches here without
        # hitting except Exception.
        # If shutdown_event is set, propagate ShutdownInterruptError so parent tool
        # result is not stored.
        if ctx.shutdown_event is not None and ctx.shutdown_event.is_set():
            raise ShutdownInterruptError(
                f"Subagent '{agent_name}' interrupted by worker shutdown"
            )

        # When only files are created without text output, include URI in result.
        # -> parent agent exposes it to user with present_file tool
        if not result_texts and result_attachments:
            result_text = "Generated files:\n" + "\n".join(
                f"- {a.uri} ({a.media_type}, {a.size} bytes)"
                for a in result_attachments
            )
        elif result_texts:
            result_text = "\n".join(result_texts)
            # Include URI even when attachments exist with text
            if result_attachments:
                result_text += "\n\nAttached files:\n" + "\n".join(
                    f"- {a.uri} ({a.media_type})" for a in result_attachments
                )
        else:
            result_text = "(no output)"

        # Publish and persist subagent_end event
        subagent_end = await _append_parent_event(
            ctx,
            make_subagent_end_event(
                session_id=ctx.parent_session_id,
                subagent_run_id=run_id,
                subagent_id=subagent_id,
                subagent_session_id=session_id,
                status="completed",
                result=result_text,
            ),
        )
        await ctx.publish_event(subagent_end)

        return json.dumps(
            {"result": result_text, "session_id": session_id},
            ensure_ascii=False,
        )

    description = _build_description(subagents)

    tool = make_tool(
        handler,
        name=SUBAGENT_TOOL_NAME,
        description=description,
        input_model=SubagentInput,
        supports_background=True,
    )

    # Add agent enum to make_tool result schema.
    # Preserve run_in_background property injected by make_tool
    schema: dict[str, object] = {**tool.spec.input_schema}
    existing_properties = schema.get("properties")
    properties: dict[str, object] = (
        {**existing_properties} if isinstance(existing_properties, dict) else {}
    )
    existing_agent = properties.get("agent")
    agent_prop: dict[str, object] = (
        {**existing_agent} if isinstance(existing_agent, dict) else {}
    )
    agent_prop["enum"] = agent_enum_values
    properties["agent"] = agent_prop
    schema["properties"] = properties

    return dataclasses.replace(
        tool,
        spec=tool.spec.model_copy(update={"input_schema": schema}),
    )
