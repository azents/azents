"""Memory tool factories for Team and User Session execution."""

import json

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.rdb.session import SessionManager
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import (
    MemoryCreate,
    MemoryScope,
    MemorySearchMatch,
    MemorySummary,
)


class SaveMemoryInput(BaseModel):
    """save_memory tool input."""

    scope: MemoryScope = Field(
        description="Memory scope. Team Sessions support agent only."
    )
    type: str = Field(
        description=(
            "Memory type: 'user' (role/expertise), 'feedback' (behavioral rules), "
            "'project' (ongoing work), or 'reference' (external system pointers)."
        )
    )
    name: str = Field(description="Memory identifier used as the upsert key.")
    description: str = Field(description="One-line summary for the memory index.")
    content: str = Field(description="Memory body in markdown.")


class ListMemoriesInput(BaseModel):
    """list_memories tool input."""

    scope: MemoryScope | None = Field(
        default=None,
        description="Filter by scope. Team Sessions return agent scope only.",
    )
    type: str | None = Field(default=None, description="Filter by memory type.")


class GetMemoryInput(BaseModel):
    """get_memory tool input."""

    scope: MemoryScope = Field(
        description="Memory scope. Team Sessions support agent only."
    )
    name: str = Field(description="Memory name.")


class SearchMemoriesInput(BaseModel):
    """search_memories tool input."""

    query: str = Field(
        description=(
            "Whitespace-separated search terms. Search returns exact all-term "
            "matches when possible, otherwise ranked partial matches."
        )
    )
    scope: MemoryScope | None = Field(
        default=None,
        description="Filter by scope. Team Sessions search agent scope only.",
    )


class DeleteMemoryInput(BaseModel):
    """delete_memory tool input."""

    scope: MemoryScope = Field(
        description="Memory scope. Team Sessions support agent only."
    )
    name: str = Field(description="Memory name.")


def _resolve_scope_user_id(
    scope: MemoryScope | None,
    *,
    associated_user_id: str | None,
) -> str | None:
    """Map requested Memory scope to the repository user_id boundary.

    :param scope: Requested scope, or None for list/search defaults
    :param associated_user_id: Root User Session owner when available
    :return: Repository user_id (None means Agent scope)
    """
    if scope is MemoryScope.USER:
        if associated_user_id is None:
            raise FunctionToolError(
                "User-scope memories are unavailable in Team Sessions"
            )
        return associated_user_id
    if scope is MemoryScope.AGENT or scope is None:
        return None
    raise FunctionToolError(f"Unsupported Memory scope: {scope}")


def _format_memory_list(
    agent_summaries: list[MemorySummary],
    *,
    title: str = "Agent Memories",
) -> str:
    """Group Memory summaries by type."""
    if not agent_summaries:
        return "No memories found."
    return "\n".join([f"## {title}", *_format_by_type(agent_summaries)])


def _format_by_type(summaries: list[MemorySummary]) -> list[str]:
    """Format summary entries grouped by memory type."""
    by_type: dict[str, list[MemorySummary]] = {}
    for summary in summaries:
        by_type.setdefault(summary.type, []).append(summary)

    lines: list[str] = []
    for memory_type in sorted(by_type):
        lines.append("")
        lines.append(f"### {memory_type.title()}")
        lines.extend(
            f"- **{summary.name}** — {summary.description}"
            for summary in by_type[memory_type]
        )
    return lines


def make_save_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Team Agent-scope Memory upsert tool."""

    async def save_memory(args: SaveMemoryInput) -> str:
        """Save or update a Memory entry for the allowed scope."""
        scope_user_id = _resolve_scope_user_id(
            args.scope,
            associated_user_id=associated_user_id,
        )
        scope = MemoryScope.USER if scope_user_id is not None else MemoryScope.AGENT
        async with session_manager() as session:
            await repo.upsert(
                session,
                agent_id=agent_id,
                user_id=scope_user_id,
                create=MemoryCreate(
                    scope=scope,
                    type=args.type,
                    name=args.name,
                    description=args.description,
                    content=args.content,
                ),
            )
        return json.dumps(
            {
                "status": "saved",
                "name": args.name,
                "scope": scope.value,
                "type": args.type,
            },
            ensure_ascii=False,
        )

    description = (
        "Save or update a Memory entry. "
        "User Sessions support agent and user scopes; Team Sessions support agent only."
        if associated_user_id is not None
        else (
            "Save or update a shared Agent Memory entry. "
            "Team Sessions support agent scope only."
        )
    )
    return make_tool(
        save_memory,
        name="save_memory",
        description=description,
    )


def make_list_memories_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Team Agent-scope Memory list tool."""

    async def list_memories(args: ListMemoriesInput) -> str:
        """List Memory entries for allowed scopes."""
        if args.scope is MemoryScope.USER and associated_user_id is None:
            raise FunctionToolError(
                "User-scope memories are unavailable in Team Sessions"
            )
        async with session_manager() as session:
            if args.scope is MemoryScope.USER:
                summaries = await repo.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=associated_user_id,
                    type=args.type,
                )
                return _format_memory_list(summaries, title="User Memories")
            if args.scope is MemoryScope.AGENT or (
                args.scope is None and associated_user_id is None
            ):
                summaries = await repo.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=None,
                    type=args.type,
                )
                return _format_memory_list(summaries)
            # User Session default: both scopes
            agent_summaries = await repo.list_summaries(
                session,
                agent_id=agent_id,
                user_id=None,
                type=args.type,
            )
            user_summaries = await repo.list_summaries(
                session,
                agent_id=agent_id,
                user_id=associated_user_id,
                type=args.type,
            )
        parts: list[str] = []
        if agent_summaries:
            parts.append(_format_memory_list(agent_summaries))
        if user_summaries:
            parts.append(_format_memory_list(user_summaries, title="User Memories"))
        return "\n\n".join(parts) if parts else "No memories found."

    return make_tool(
        list_memories,
        name="list_memories",
        description=(
            "List shared Agent Memory and optional associated User Memory entries."
            if associated_user_id is not None
            else "List shared Agent Memory entries by optional type."
        ),
    )


def make_get_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Team Agent-scope Memory read tool."""

    async def get_memory(args: GetMemoryInput) -> str:
        """Read one Memory entry for the allowed scope."""
        scope_user_id = _resolve_scope_user_id(
            args.scope,
            associated_user_id=associated_user_id,
        )
        async with session_manager() as session:
            memory = await repo.get_by_name(
                session,
                agent_id=agent_id,
                user_id=scope_user_id,
                name=args.name,
            )
        if memory is None:
            scope_label = "user" if scope_user_id is not None else "agent"
            raise FunctionToolError(
                f"Memory '{args.name}' not found in {scope_label} scope"
            )
        return (
            f"# {memory.name} ({memory.type}, {memory.scope.value} scope)\n\n"
            f"{memory.content}\n\n---\n"
            f"Created: {memory.created_at:%Y-%m-%d} | "
            f"Updated: {memory.updated_at:%Y-%m-%d}"
        )

    return make_tool(
        get_memory,
        name="get_memory",
        description="Retrieve one shared Agent Memory entry by exact name.",
    )


def make_search_memories_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Team Agent-scope Memory search tool."""

    async def search_memories(args: SearchMemoriesInput) -> str:
        """Search allowed Memory scopes with an exact-to-partial fallback."""
        if args.scope is MemoryScope.USER and associated_user_id is None:
            raise FunctionToolError(
                "User-scope memories are unavailable in Team Sessions"
            )
        scope_user_id = associated_user_id if args.scope is MemoryScope.USER else None
        include_agent_scope = args.scope is not MemoryScope.USER
        if args.scope is None and associated_user_id is not None:
            # Search both scopes by preferring user filter with agent included.
            scope_user_id = associated_user_id
            include_agent_scope = True
        async with session_manager() as session:
            results = await repo.search(
                session,
                agent_id=agent_id,
                user_id=scope_user_id,
                include_agent_scope=include_agent_scope,
                query=args.query,
            )
            partial_results: list[MemorySearchMatch] = []
            if not results:
                partial_results = await repo.search_partial(
                    session,
                    agent_id=agent_id,
                    user_id=scope_user_id,
                    include_agent_scope=include_agent_scope,
                    query=args.query,
                )
        if results:
            return "\n".join(
                f"{index}. **{memory.name}** ({memory.type}) — {memory.description}"
                for index, memory in enumerate(results, 1)
            )
        if partial_results:
            lines = ["No exact all-term match was found.", "", "Partial matches:"]
            lines.extend(
                f"{index}. **{memory.name}** ({memory.type}) — {memory.description} "
                f"(matched {memory.matched_terms}/{memory.total_terms} terms)"
                for index, memory in enumerate(partial_results, 1)
            )
            return "\n".join(lines)
        return (
            f'No lexical candidates found for "{args.query}". '
            "Check the loaded memory summaries before creating a new memory."
        )

    return make_tool(
        search_memories,
        name="search_memories",
        description=(
            "Search shared Agent Memory with exact all-term and partial-match results."
        ),
    )


def make_delete_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Team Agent-scope Memory delete tool."""

    async def delete_memory(args: DeleteMemoryInput) -> str:
        """Delete one Memory entry for the allowed scope."""
        scope_user_id = _resolve_scope_user_id(
            args.scope,
            associated_user_id=associated_user_id,
        )
        scope = MemoryScope.USER if scope_user_id is not None else MemoryScope.AGENT
        async with session_manager() as session:
            deleted = await repo.delete_by_name(
                session,
                agent_id=agent_id,
                user_id=scope_user_id,
                name=args.name,
            )
        if not deleted:
            scope_label = scope.value
            raise FunctionToolError(
                f"Memory '{args.name}' not found in {scope_label} scope"
            )
        return json.dumps(
            {
                "status": "deleted",
                "name": args.name,
                "scope": scope.value,
            },
            ensure_ascii=False,
        )

    return make_tool(
        delete_memory,
        name="delete_memory",
        description="Delete one shared Agent Memory entry by exact name.",
    )
