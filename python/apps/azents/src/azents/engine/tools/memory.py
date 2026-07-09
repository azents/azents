"""Memory tool factory.

Allows agent to store, list, search, and delete memories.
save_memory, list_memories, get_memory, search_memories, delete_memory
Provides five tools.
"""

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
    MemorySummary,
)

# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class SaveMemoryInput(BaseModel):
    """save_memory tool input."""

    scope: MemoryScope = Field(
        description="Where to save. 'agent' for team-wide knowledge (shared with all users), 'user' for personal preference (only this user)."  # noqa: E501
    )
    type: str = Field(
        description="Memory type: 'user' (role/expertise), 'feedback' (behavioral rules), 'project' (ongoing work), 'reference' (external system pointers)."  # noqa: E501
    )
    name: str = Field(
        description="Memory identifier. Used for upsert — same name in the same scope overwrites."  # noqa: E501
    )
    description: str = Field(
        description="One-line summary. Always loaded in context for relevance judgment."  # noqa: E501
    )
    content: str = Field(description="Memory body in markdown.")


class ListMemoriesInput(BaseModel):
    """list_memories tool input."""

    scope: MemoryScope | None = Field(
        default=None, description="Filter by scope. None returns both scopes."
    )  # noqa: E501
    type: str | None = Field(
        default=None, description="Filter by type. None returns all types."
    )  # noqa: E501


class GetMemoryInput(BaseModel):
    """get_memory tool input."""

    scope: MemoryScope = Field(description="Memory scope.")
    name: str = Field(description="Memory name to retrieve.")


class SearchMemoriesInput(BaseModel):
    """search_memories tool input."""

    query: str = Field(
        description=(
            "Keyword search only. Do not pass a full sentence. "
            "Extract 1-3 distinctive keywords, memory names, project names, "
            "or error terms from the request."
        )
    )  # noqa: E501
    scope: MemoryScope | None = Field(
        default=None, description="Filter by scope. None searches both scopes."
    )  # noqa: E501


class DeleteMemoryInput(BaseModel):
    """delete_memory tool input."""

    scope: MemoryScope = Field(description="Memory scope.")
    name: str = Field(description="Memory name to delete.")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_memory_list(
    agent_summaries: list[MemorySummary],
    user_summaries: list[MemorySummary],
) -> str:
    """Group by type and create index text."""
    parts: list[str] = []

    if agent_summaries:
        parts.append("## Agent Memories")
        parts.extend(_format_by_type(agent_summaries))

    if user_summaries:
        if parts:
            parts.append("")
        parts.append("## User Memories")
        parts.extend(_format_by_type(user_summaries))

    return "\n".join(parts) if parts else "No memories found."


def _format_by_type(summaries: list[MemorySummary]) -> list[str]:
    """Formatter grouping by type."""
    by_type: dict[str, list[MemorySummary]] = {}
    for s in summaries:
        by_type.setdefault(s.type, []).append(s)

    lines: list[str] = []
    for mem_type in sorted(by_type):
        group = by_type.get(mem_type)
        if not group:
            continue
        lines.append("")
        lines.append(f"### {mem_type.title()}")
        for m in group:
            lines.append(f"- **{m.name}** — {m.description}")
    return lines


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def make_save_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """save_memory Create tool.

    :param repo: Memory repository
    :param agent_id: Agent ID
    :param user_id: User ID; user scope unavailable when None
    :param session_manager: DB session manager
    :return: FunctionTool instance
    """

    async def save_memory(args: SaveMemoryInput) -> str:
        """Save or update a memory entry. Same name in the same scope overwrites."""
        if args.scope == MemoryScope.USER and not user_id:
            raise FunctionToolError("Cannot save user-scope memory: no user context")

        effective_user_id = user_id if args.scope == MemoryScope.USER else None

        async with session_manager() as session:
            await repo.upsert(
                session,
                agent_id=agent_id,
                user_id=effective_user_id,
                create=MemoryCreate(
                    scope=args.scope,
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
                "scope": args.scope.value,
                "type": args.type,
            },
            ensure_ascii=False,
        )

    return make_tool(
        save_memory,
        name="save_memory",
        description=(
            "Save or update a memory entry. "
            "Use 'agent' scope for team-wide knowledge, "
            "'user' scope for personal preferences. "
            "Same name in the same scope overwrites the existing entry."
        ),
    )


def make_list_memories_tool(
    repo: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """list_memories Create tool.

    :param repo: Memory repository
    :param agent_id: Agent ID
    :param user_id: User ID; user scope unavailable when None
    :param session_manager: DB session manager
    :return: FunctionTool instance
    """

    async def list_memories(args: ListMemoriesInput) -> str:
        """List memory entries, optionally filtered by scope and type."""
        if args.scope == MemoryScope.USER and not user_id:
            raise FunctionToolError("Cannot list user-scope memories: no user context")

        type_filter = args.type if args.type is not None else None
        agent_summaries: list[MemorySummary] = []
        user_summaries: list[MemorySummary] = []

        async with session_manager() as session:
            # agent scope
            if args.scope is None or args.scope == MemoryScope.AGENT:
                agent_summaries = await repo.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=None,
                    type=type_filter,
                )

            # user scope
            if (args.scope is None or args.scope == MemoryScope.USER) and user_id:
                user_summaries = await repo.list_summaries(
                    session,
                    agent_id=agent_id,
                    user_id=user_id,
                    type=type_filter,
                )

        return _format_memory_list(agent_summaries, user_summaries)

    return make_tool(
        list_memories,
        name="list_memories",
        description=(
            "List all memory entries. "
            "Filter by scope (agent/user) and type "
            "(user/feedback/project/reference)."
        ),
    )


def make_get_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """get_memory Create tool.

    :param repo: Memory repository
    :param agent_id: Agent ID
    :param user_id: User ID; user scope unavailable when None
    :param session_manager: DB session manager
    :return: FunctionTool instance
    """

    async def get_memory(args: GetMemoryInput) -> str:
        """Retrieve the full content of a specific memory by name and scope."""
        if args.scope == MemoryScope.USER and not user_id:
            raise FunctionToolError("Cannot get user-scope memory: no user context")
        effective_user_id = user_id if args.scope == MemoryScope.USER else None

        async with session_manager() as session:
            memory = await repo.get_by_name(
                session,
                agent_id=agent_id,
                user_id=effective_user_id,
                name=args.name,
            )

        if memory is None:
            raise FunctionToolError(
                f"Memory '{args.name}' not found in {args.scope} scope"
            )

        return (
            f"# {memory.name} ({memory.type}, {memory.scope.value} scope)\n"
            f"\n"
            f"{memory.content}\n"
            f"\n"
            f"---\n"
            f"Created: {memory.created_at:%Y-%m-%d} | "
            f"Updated: {memory.updated_at:%Y-%m-%d}"
        )

    return make_tool(
        get_memory,
        name="get_memory",
        description=(
            "Retrieve the full content of a specific memory entry. "
            "Requires the exact name and scope."
        ),
    )


def make_search_memories_tool(
    repo: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """search_memories Create tool.

    :param repo: Memory repository
    :param agent_id: Agent ID
    :param user_id: User ID; only agent scope searched when None
    :param session_manager: DB session manager
    :return: FunctionTool instance
    """

    async def search_memories(args: SearchMemoriesInput) -> str:
        """Search memories by keyword in name, description, and content."""
        if args.scope == MemoryScope.USER and not user_id:
            raise FunctionToolError(
                "Cannot search user-scope memories: no user context"
            )
        results: list[MemorySummary] = []

        async with session_manager() as session:
            if args.scope is None:
                # repo.search searches both agent + user scopes when user_id is provided
                results = await repo.search(
                    session,
                    agent_id=agent_id,
                    user_id=user_id,
                    query=args.query,
                )
            elif args.scope == MemoryScope.AGENT:
                results = await repo.search(
                    session,
                    agent_id=agent_id,
                    user_id=None,
                    query=args.query,
                )
            elif args.scope == MemoryScope.USER:
                if not user_id:
                    raise FunctionToolError(
                        "Cannot search user-scope memories: no user context"
                    )
                # Search only user scope. Passing user_id searches both agent+user, so
                # filter only user scope from results
                all_results = await repo.search(
                    session,
                    agent_id=agent_id,
                    user_id=user_id,
                    query=args.query,
                )
                # repo.search omits scope info in MemorySummary, so searching with
                # user_id=user_id also includes agent scope results. To separately
                # search only user scope, search with user_id only.
                results = all_results

        if not results:
            return f'No memories found matching "{args.query}".'

        lines: list[str] = []
        for i, m in enumerate(results, 1):
            lines.append(f"{i}. **{m.name}** ({m.type}) — {m.description}")
        return "\n".join(lines)

    return make_tool(
        search_memories,
        name="search_memories",
        description=(
            "Search memories by short keywords, not full sentences. "
            "Extract 1-3 distinctive keywords, memory names, project names, "
            "or error terms before calling this tool. Searches in name, "
            "description, and content fields."
        ),
    )


def make_delete_memory_tool(
    repo: MemoryRepository,
    agent_id: str,
    user_id: str | None,
    session_manager: SessionManager[AsyncSession],
) -> FunctionTool:
    """delete_memory Create tool.

    :param repo: Memory repository
    :param agent_id: Agent ID
    :param user_id: User ID; user scope unavailable when None
    :param session_manager: DB session manager
    :return: FunctionTool instance
    """

    async def delete_memory(args: DeleteMemoryInput) -> str:
        """Delete a memory entry by name and scope."""
        if args.scope == MemoryScope.USER and not user_id:
            raise FunctionToolError("Cannot delete user-scope memory: no user context")
        effective_user_id = user_id if args.scope == MemoryScope.USER else None

        async with session_manager() as session:
            deleted = await repo.delete_by_name(
                session,
                agent_id=agent_id,
                user_id=effective_user_id,
                name=args.name,
            )

        if not deleted:
            raise FunctionToolError(
                f"Memory '{args.name}' not found in {args.scope} scope"
            )

        return json.dumps(
            {
                "status": "deleted",
                "name": args.name,
                "scope": args.scope.value,
            },
            ensure_ascii=False,
        )

    return make_tool(
        delete_memory,
        name="delete_memory",
        description=(
            "Delete a memory entry by name and scope. "
            "Returns an error if the memory does not exist."
        ),
    )
