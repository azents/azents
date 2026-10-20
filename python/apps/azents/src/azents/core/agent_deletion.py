"""Pure Agent deletion ownership, execution identity and completion contracts."""

import dataclasses
import enum
from collections.abc import Iterable

from azents.core.session_lifecycle_schema import PostgreSQLForeignKeyDeleteAction
from azents.core.upload_images import StoredImage


class AgentDeletionPolicy(enum.StrEnum):
    """Authority exercised before a parent row can be removed."""

    REQUIRE_ABSENT = "require_absent"
    DECLARED_CASCADE = "declared_cascade"
    PRESERVE_DETACHED = "preserve_detached"
    VERIFY_RUNTIME = "verify_runtime"


@dataclasses.dataclass(frozen=True)
class AgentDeletionContext:
    """Exact current job ownership; never reusable across claimed attempts."""

    job_id: str
    agent_id: str
    workspace_id: str
    lease_owner: str
    expected_attempt: int


@dataclasses.dataclass(frozen=True)
class AgentDeletionRelationship:
    """One column-scoped installed relationship with an explicit cleanup owner."""

    source_table: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]
    delete_action: PostgreSQLForeignKeyDeleteAction
    policy: AgentDeletionPolicy

    @property
    def key(self) -> str:
        """Return an unambiguous diagnostic identity without database values."""
        return f"{self.source_table}({','.join(self.source_columns)})"


@dataclasses.dataclass(frozen=True)
class AgentDeletionParticipantDefinition:
    """One executable responsibility and all its database/external obligations."""

    key: str
    dependencies: tuple[str, ...]
    relationships: tuple[AgentDeletionRelationship, ...]
    external_resources: tuple[str, ...]
    historical_resources: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class AgentAvatarDeletionEvidence:
    """Successful current-attempt deletion of one immutable avatar target set."""

    context: AgentDeletionContext
    keys: tuple[str, ...]


def avatar_object_keys(avatar: StoredImage | None) -> tuple[str, ...]:
    """Describe the exact deduplicated target used by avatar object deletion."""
    if avatar is None:
        return ()
    return tuple(
        sorted(
            {
                file.key
                for file in (
                    avatar.default,
                    avatar.original,
                    avatar.thumbnails.small,
                    avatar.thumbnails.medium,
                    avatar.thumbnails.large,
                )
                if file is not None
            }
        )
    )


class AgentDeletionOwnershipLost(RuntimeError):
    """An obsolete worker cannot mutate or complete a deletion job."""


class AgentDeletionParticipantFailure(RuntimeError):
    """Attributable failure retaining the original exception as its cause."""

    def __init__(self, *, participant_key: str, phase: str, error: Exception) -> None:
        self.participant_key = participant_key
        self.phase = phase
        self.error = error
        super().__init__(f"Agent deletion {participant_key}/{phase} failed: {error}")


@dataclasses.dataclass(frozen=True, init=False)
class AgentDeletionRegistry:
    """Validated deterministic composition shared by execution and verification."""

    participants: tuple[AgentDeletionParticipantDefinition, ...]

    def __init__(
        self, participants: Iterable[AgentDeletionParticipantDefinition]
    ) -> None:
        definitions = tuple(participants)
        by_key = {item.key: item for item in definitions}
        if len(by_key) != len(definitions):
            raise ValueError("Duplicate Agent deletion participant")
        relationships: set[tuple[str, tuple[str, ...]]] = set()
        external: set[str] = set()
        historical: set[str] = set()
        for definition in definitions:
            if not definition.key or len(definition.key) > 80:
                raise ValueError("Invalid Agent deletion participant key")
            if any(key not in by_key for key in definition.dependencies):
                raise ValueError("Unknown Agent deletion dependency")
            for relation in definition.relationships:
                identity = (relation.source_table, relation.source_columns)
                if identity in relationships:
                    raise ValueError(
                        f"Duplicate Agent deletion ownership: {relation.key}"
                    )
                relationships.add(identity)
                if not relation.source_columns or len(relation.source_columns) != len(
                    relation.target_columns
                ):
                    raise ValueError(
                        f"Invalid Agent deletion relationship: {relation.key}"
                    )
            for declared, seen in (
                (definition.external_resources, external),
                (definition.historical_resources, historical),
            ):
                for resource in declared:
                    if resource in seen:
                        raise ValueError(
                            f"Duplicate Agent deletion resource: {resource}"
                        )
                    seen.add(resource)
        ordered: list[AgentDeletionParticipantDefinition] = []
        pending = list(definitions)
        completed: set[str] = set()
        while pending:
            ready = next(
                (item for item in pending if set(item.dependencies) <= completed), None
            )
            if ready is None:
                raise ValueError("Cyclic Agent deletion dependencies")
            ordered.append(ready)
            completed.add(ready.key)
            pending.remove(ready)
        object.__setattr__(self, "participants", tuple(ordered))

    def require_handlers(self, keys: Iterable[str]) -> None:
        """Reject missing or extra implementations before any side effects."""
        actual = tuple(keys)
        expected = {item.key for item in self.participants}
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("Agent deletion handlers do not match the registry")
