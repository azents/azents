"""Agent-scope Memory tool factory for Team Session execution."""

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


def _require_agent_scope(scope: MemoryScope | None) -> None:
    """Reject User-scope Memory from Team Session execution."""
    if scope == MemoryScope.USER:
        raise FunctionToolError("User-scope memories are unavailable in Team Sessions")


def _format_memory_list(agent_summaries: list[MemorySummary]) -> str:
    """Group Agent Memory summaries by type."""
    if not agent_summaries:
        return "No memories found."
    return "\n".join(["## Agent Memories", *_format_by_type(agent_summaries)])


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
) -> FunctionTool:
    """Create the Team Agent-scope Memory upsert tool."""

    async def save_memory(args: SaveMemoryInput) -> str:
        """Save or update an Agent-scope Memory entry."""
        _require_agent_scope(args.scope)
        async with session_manager() as session:
            await repo.upsert(
                session,
                agent_id=agent_id,
                user_id=None,
                create=MemoryCreate(
                    scope=MemoryScope.AGENT,
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
                "scope": MemoryScope.AGENT.value,
                "type": args.type,
            },
            ensure_ascii=False,
        )

    return make_tool(
        save_memory,
        name="save_memory",
        description=(
            "Save or update a shared Agent Memory entry. "
            "Team Sessions support agent scope only."
        ),
    )


def make_list_memories_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """Create the Team Agent-scope Memory list tool."""

    async def list_memories(args: ListMemoriesInput) -> str:
        """List Agent-scope Memory entries."""
        _require_agent_scope(args.scope)
        async with session_manager() as session:
            summaries = await repo.list_summaries(
                session,
                agent_id=agent_id,
                user_id=None,
                type=args.type,
            )
        return _format_memory_list(summaries)

    return make_tool(
        list_memories,
        name="list_memories",
        description="List shared Agent Memory entries by optional type.",
    )


def make_get_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """Create the Team Agent-scope Memory read tool."""

    async def get_memory(args: GetMemoryInput) -> str:
        """Read one Agent-scope Memory entry."""
        _require_agent_scope(args.scope)
        async with session_manager() as session:
            memory = await repo.get_by_name(
                session,
                agent_id=agent_id,
                user_id=None,
                name=args.name,
            )
        if memory is None:
            raise FunctionToolError(f"Memory '{args.name}' not found in agent scope")
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
) -> FunctionTool:
    """Create the Team Agent-scope Memory search tool."""

    async def search_memories(args: SearchMemoriesInput) -> str:
        """Search Agent-scope Memory with an exact-to-partial fallback."""
        _require_agent_scope(args.scope)
        async with session_manager() as session:
            results = await repo.search(
                session,
                agent_id=agent_id,
                user_id=None,
                include_agent_scope=True,
                query=args.query,
            )
            partial_results: list[MemorySearchMatch] = []
            if not results:
                partial_results = await repo.search_partial(
                    session,
                    agent_id=agent_id,
                    user_id=None,
                    include_agent_scope=True,
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
) -> FunctionTool:
    """Create the Team Agent-scope Memory delete tool."""

    async def delete_memory(args: DeleteMemoryInput) -> str:
        """Delete one Agent-scope Memory entry."""
        _require_agent_scope(args.scope)
        async with session_manager() as session:
            deleted = await repo.delete_by_name(
                session,
                agent_id=agent_id,
                user_id=None,
                name=args.name,
            )
        if not deleted:
            raise FunctionToolError(f"Memory '{args.name}' not found in agent scope")
        return json.dumps(
            {
                "status": "deleted",
                "name": args.name,
                "scope": MemoryScope.AGENT.value,
            },
            ensure_ascii=False,
        )

    return make_tool(
        delete_memory,
        name="delete_memory",
        description="Delete one shared Agent Memory entry by exact name.",
    )
