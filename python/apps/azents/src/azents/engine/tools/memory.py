"""Saved Memory mutation tool factories for Team and User Session execution."""

import json

from pydantic import BaseModel, ConfigDict, Field

from azents.core.memory_scope import MemoryScope
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.repos.memory.data import MemoryCreate
from azents.repos.memory.operations import MemoryOperationRepository


class SaveMemoryInput(BaseModel):
    """save_memory tool input."""

    model_config = ConfigDict(extra="forbid")

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


class DeleteMemoryInput(BaseModel):
    """delete_memory tool input."""

    model_config = ConfigDict(extra="forbid")

    scope: MemoryScope = Field(
        description="Memory scope. Team Sessions support agent only."
    )
    name: str = Field(description="Memory name.")


def _resolve_scope_user_id(
    scope: MemoryScope,
    *,
    associated_user_id: str | None,
) -> str | None:
    """Map requested Memory scope to the repository user boundary."""
    if scope is MemoryScope.USER:
        if associated_user_id is None:
            raise FunctionToolError(
                "User-scope memories are unavailable in Team Sessions"
            )
        return associated_user_id
    if scope is MemoryScope.AGENT:
        return None
    raise FunctionToolError(f"Unsupported Memory scope: {scope}")


def make_save_memory_tool(
    operations: MemoryOperationRepository,
    agent_id: str,
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Saved Memory upsert tool for authorized scopes."""

    async def save_memory(args: SaveMemoryInput) -> str:
        """Save or update one Saved Memory entry for the allowed scope."""
        scope_user_id = _resolve_scope_user_id(
            args.scope,
            associated_user_id=associated_user_id,
        )
        scope = MemoryScope.USER if scope_user_id is not None else MemoryScope.AGENT
        await operations.save(
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
        "Save or update a Saved Memory entry. User Sessions support agent and "
        "user scopes; Team Sessions support agent only."
        if associated_user_id is not None
        else (
            "Save or update a shared Agent Saved Memory entry. "
            "Team Sessions support agent scope only."
        )
    )
    return make_tool(
        save_memory,
        name="save_memory",
        description=description,
    )


def make_delete_memory_tool(
    operations: MemoryOperationRepository,
    agent_id: str,
    *,
    associated_user_id: str | None = None,
) -> FunctionTool:
    """Create the Saved Memory delete tool for authorized scopes."""

    async def delete_memory(args: DeleteMemoryInput) -> str:
        """Delete one Saved Memory entry for the allowed scope."""
        scope_user_id = _resolve_scope_user_id(
            args.scope,
            associated_user_id=associated_user_id,
        )
        scope = MemoryScope.USER if scope_user_id is not None else MemoryScope.AGENT
        deleted = await operations.delete(
            agent_id=agent_id,
            user_id=scope_user_id,
            name=args.name,
        )
        if not deleted:
            raise FunctionToolError(
                f"Memory '{args.name}' not found in {scope.value} scope"
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
        description="Delete one Saved Memory entry by exact name.",
    )
