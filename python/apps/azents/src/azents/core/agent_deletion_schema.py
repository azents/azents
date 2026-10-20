"""Pure installed-edge coverage for Agent deletion ownership contracts."""

import dataclasses
from collections.abc import Iterable

from azents.core.agent_deletion import AgentDeletionPolicy, AgentDeletionRegistry
from azents.core.session_lifecycle_schema import (
    PostgreSQLForeignKey,
    PostgreSQLForeignKeyDeleteAction,
)


@dataclasses.dataclass(frozen=True)
class AgentDeletionSchemaValidation:
    """Detached diagnostics; validation never changes the installed schema."""

    violations: tuple[str, ...]

    def require_safe(self) -> None:
        if self.violations:
            raise RuntimeError(
                "Unsafe Agent deletion ownership:\n" + "\n".join(self.violations)
            )


def validate_agent_deletion_schema(
    *, registry: AgentDeletionRegistry, foreign_keys: Iterable[PostgreSQLForeignKey]
) -> AgentDeletionSchemaValidation:
    """Check all incoming root/cascade edges, including non-mutating blockers.

    Restrictive and detached children are boundaries, not permission to adopt their
    lifecycle. Their native completion/preservation obligations stay with the registry.
    """
    installed = tuple(foreign_keys)
    declarations = {
        (relation.source_table, relation.source_columns): relation
        for participant in registry.participants
        for relation in participant.relationships
    }
    visited: set[str] = set()
    matched: set[tuple[str, tuple[str, ...]]] = set()
    pending = ["agents", "agent_runtimes"]
    violations: list[str] = []
    while pending:
        parent = pending.pop()
        if parent in visited:
            continue
        visited.add(parent)
        for edge in installed:
            if edge.target_table != f"public.{parent}":
                continue
            source = edge.source_table.removeprefix("public.")
            identity = (source, edge.source_columns)
            declaration = declarations.get(identity)
            if declaration is None:
                violations.append(
                    f"Unclassified reference: {edge.constraint_name} {identity}"
                )
            else:
                matched.add(identity)
                if (
                    declaration.target_table != parent
                    or declaration.target_columns != edge.target_columns
                    or declaration.delete_action is not edge.delete_action
                ):
                    violations.append(
                        f"Relationship drift: {edge.constraint_name} {identity}"
                    )
                if (
                    declaration.policy is AgentDeletionPolicy.DECLARED_CASCADE
                    and edge.delete_action
                    is not PostgreSQLForeignKeyDeleteAction.CASCADE
                ):
                    violations.append(f"Declared child is not CASCADE: {identity}")
                if not edge.triggers:
                    violations.append(
                        f"Missing referential triggers: {edge.constraint_name}"
                    )
            if edge.delete_action is PostgreSQLForeignKeyDeleteAction.CASCADE:
                pending.append(source)
    for identity in declarations.keys() - matched:
        violations.append(f"Declared relationship is absent: {identity}")
    return AgentDeletionSchemaValidation(tuple(sorted(violations)))
