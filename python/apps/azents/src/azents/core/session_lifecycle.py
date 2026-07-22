"""Session lifecycle participant contracts and immutable registry."""

import dataclasses
import enum
from collections.abc import Iterable
from types import MappingProxyType
from typing import Mapping, Protocol


class SessionLifecycleResourceKind(enum.StrEnum):
    """Kind of resource declared by a lifecycle participant."""

    DATABASE_TABLE = "database_table"
    EXTERNAL_RESOURCE = "external_resource"


class SessionLifecycleResourceClassification(enum.StrEnum):
    """Deletion ownership classification for a declared resource."""

    LIFECYCLE_ROOT = "lifecycle_root"
    PURE_DATABASE_CHILD = "pure_database_child"
    ORCHESTRATOR_ROOT = "orchestrator_root"


class SessionLifecycleTransitionPolicy(enum.StrEnum):
    """Archive or restore behavior declared by a participant."""

    MUTATE = "mutate"
    VALIDATE = "validate"
    PRESERVE = "preserve"
    TERMINATE = "terminate"


class SessionLifecyclePurgePolicy(enum.StrEnum):
    """Purge behavior declared by a participant."""

    REQUIRED = "required"
    DECLARED_CASCADE = "declared_cascade"


@dataclasses.dataclass(frozen=True)
class SessionLifecycleResource:
    """One database or external resource owned by a participant."""

    kind: SessionLifecycleResourceKind
    name: str
    classification: SessionLifecycleResourceClassification
    test_node_id: str


@dataclasses.dataclass(frozen=True)
class SessionLifecycleParticipantDefinition:
    """Immutable metadata and policy contract for one lifecycle participant."""

    key: str
    policy_version: int
    dependencies: tuple[str, ...]
    owned_resources: tuple[SessionLifecycleResource, ...]
    archive_policy: SessionLifecycleTransitionPolicy
    restore_policy: SessionLifecycleTransitionPolicy
    purge_policy: SessionLifecyclePurgePolicy


@dataclasses.dataclass(frozen=True)
class SessionLifecycleTransitionContext:
    """Locked root-tree identity passed to archive and restore participants."""

    transition_id: str
    root_session_id: str
    subtree_session_ids: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class SessionLifecyclePurgeContext:
    """Fenced purge identity passed to purge participants."""

    purge_job_id: str
    lease_owner: str
    root_session_id: str
    subtree_session_ids: tuple[str, ...]


class SessionLifecycleParticipant(Protocol):
    """Executable participant contract implemented during lifecycle cutover."""

    @property
    def definition(self) -> SessionLifecycleParticipantDefinition:
        """Return immutable participant metadata."""
        ...

    async def validate_archive(
        self, context: SessionLifecycleTransitionContext
    ) -> None:
        """Validate archive eligibility inside the orchestrator transaction."""

    async def archive(self, context: SessionLifecycleTransitionContext) -> None:
        """Apply archive-local database mutation inside the orchestrator transaction."""

    async def validate_restore(
        self, context: SessionLifecycleTransitionContext
    ) -> None:
        """Validate restore eligibility inside the orchestrator transaction."""

    async def restore(self, context: SessionLifecycleTransitionContext) -> None:
        """Apply restore-local database mutation inside the orchestrator transaction."""

    async def prepare_purge(self, context: SessionLifecyclePurgeContext) -> None:
        """Prepare durable participant-owned purge state."""

    async def cleanup_purge(self, context: SessionLifecyclePurgeContext) -> None:
        """Perform idempotent participant-owned external purge cleanup."""

    async def verify_purge(self, context: SessionLifecyclePurgeContext) -> None:
        """Verify participant-owned cleanup from authoritative domain state."""

    async def finalize_purge(self, context: SessionLifecyclePurgeContext) -> None:
        """Finalize participant-owned database state in the final transaction."""


class SessionLifecycleParticipantNotRegistered(ValueError):
    """Raised when a requested participant key is not in the active registry."""


class SessionLifecycleParticipantVersionUnsupported(ValueError):
    """Raised when an incomplete job references an unavailable policy version."""


@dataclasses.dataclass(frozen=True, init=False)
class SessionLifecycleRegistry:
    """Validated immutable participant registry with deterministic dependency order."""

    _participants_by_key: Mapping[str, SessionLifecycleParticipantDefinition]
    _ordered_participants: tuple[SessionLifecycleParticipantDefinition, ...]

    def __init__(
        self,
        participants: Iterable[SessionLifecycleParticipantDefinition],
    ) -> None:
        participant_items = tuple(participants)
        by_key: dict[str, SessionLifecycleParticipantDefinition] = {}
        resource_owners: dict[
            tuple[SessionLifecycleResourceKind, str],
            SessionLifecycleParticipantDefinition,
        ] = {}

        for participant in participant_items:
            if participant.policy_version < 1:
                raise ValueError(
                    "Session lifecycle participant policy versions must start at 1: "
                    f"{participant.key}"
                )
            if participant.key in by_key:
                raise ValueError(
                    f"Duplicate session lifecycle participant key: {participant.key}"
                )
            self._validate_transition_policies(participant)
            for resource in participant.owned_resources:
                owner_key = (resource.kind, resource.name)
                existing_owner = resource_owners.get(owner_key)
                if existing_owner is not None:
                    raise ValueError(
                        "Overlapping session lifecycle resource ownership: "
                        f"{resource.kind.value}:{resource.name} is owned by "
                        f"{existing_owner.key} and {participant.key}"
                    )
                if (
                    resource.classification
                    is SessionLifecycleResourceClassification.LIFECYCLE_ROOT
                    and participant.purge_policy
                    is not SessionLifecyclePurgePolicy.REQUIRED
                ):
                    raise ValueError(
                        "Lifecycle roots require an explicit purge policy: "
                        f"{participant.key}:{resource.name}"
                    )
                resource_owners[owner_key] = participant
            by_key[participant.key] = participant

        for participant in participant_items:
            for dependency in participant.dependencies:
                if dependency == participant.key:
                    raise ValueError(
                        "Session lifecycle participant cannot depend on itself: "
                        f"{participant.key}"
                    )
                if dependency not in by_key:
                    raise ValueError(
                        "Session lifecycle participant dependency is not registered: "
                        f"{participant.key} -> {dependency}"
                    )

        object.__setattr__(
            self,
            "_participants_by_key",
            MappingProxyType(by_key),
        )
        object.__setattr__(
            self,
            "_ordered_participants",
            self._topological_order(by_key),
        )

    @property
    def participants(self) -> tuple[SessionLifecycleParticipantDefinition, ...]:
        """Return participants in stable dependency order."""
        return self._ordered_participants

    def get(self, key: str) -> SessionLifecycleParticipantDefinition:
        """Return one registered participant by stable key."""
        try:
            return self._participants_by_key[key]
        except KeyError as error:
            raise SessionLifecycleParticipantNotRegistered(key) from error

    def require_policy_version(
        self,
        *,
        key: str,
        policy_version: int,
    ) -> SessionLifecycleParticipantDefinition:
        """Return a participant only when its persisted policy version is supported."""
        participant = self.get(key)
        if participant.policy_version != policy_version:
            raise SessionLifecycleParticipantVersionUnsupported(
                f"{key}@{policy_version}"
            )
        return participant

    @staticmethod
    def _validate_transition_policies(
        participant: SessionLifecycleParticipantDefinition,
    ) -> None:
        """Reject unsupported archive and restore policy combinations."""
        archive_policy = participant.archive_policy
        restore_policy = participant.restore_policy
        if restore_policy is SessionLifecycleTransitionPolicy.TERMINATE:
            raise ValueError(
                "Session lifecycle restore policy cannot terminate a participant: "
                f"{participant.key}"
            )
        if archive_policy is SessionLifecycleTransitionPolicy.TERMINATE:
            if restore_policy is not SessionLifecycleTransitionPolicy.PRESERVE:
                raise ValueError(
                    "Session lifecycle termination policy requires restore preserve: "
                    f"{participant.key}"
                )
            return
        if (
            archive_policy is SessionLifecycleTransitionPolicy.MUTATE
            or restore_policy is SessionLifecycleTransitionPolicy.MUTATE
        ) and (
            archive_policy is not SessionLifecycleTransitionPolicy.MUTATE
            or restore_policy is not SessionLifecycleTransitionPolicy.MUTATE
        ):
            raise ValueError(
                "Session lifecycle archive and restore mutation policies must "
                f"be symmetric: {participant.key}"
            )
        if (
            archive_policy is SessionLifecycleTransitionPolicy.PRESERVE
            and restore_policy is SessionLifecycleTransitionPolicy.VALIDATE
        ):
            raise ValueError(
                "Session lifecycle restore validation requires archive validation: "
                f"{participant.key}"
            )

    @staticmethod
    def _topological_order(
        by_key: Mapping[str, SessionLifecycleParticipantDefinition],
    ) -> tuple[SessionLifecycleParticipantDefinition, ...]:
        remaining_dependencies = {
            key: set(participant.dependencies) for key, participant in by_key.items()
        }
        ordered: list[SessionLifecycleParticipantDefinition] = []

        while remaining_dependencies:
            ready = sorted(
                key
                for key, dependencies in remaining_dependencies.items()
                if not dependencies
            )
            if not ready:
                cycle = ", ".join(sorted(remaining_dependencies))
                raise ValueError(
                    f"Session lifecycle participant dependency cycle: {cycle}"
                )
            for key in ready:
                ordered.append(by_key[key])
                del remaining_dependencies[key]
            completed = set(ready)
            for dependencies in remaining_dependencies.values():
                dependencies.difference_update(completed)

        return tuple(ordered)


@dataclasses.dataclass(frozen=True)
class SessionLifecycleOwnershipManifest:
    """Immutable catalog coverage manifest derived from participant ownership."""

    resources: tuple[SessionLifecycleResource, ...]

    def __post_init__(self) -> None:
        database_resources = [
            resource
            for resource in self.resources
            if resource.kind is SessionLifecycleResourceKind.DATABASE_TABLE
        ]
        names = [resource.name for resource in database_resources]
        if len(names) != len(set(names)):
            raise ValueError(
                "Session lifecycle ownership manifest has duplicate database tables."
            )

    def database_resource(self, table_name: str) -> SessionLifecycleResource | None:
        """Return the ownership declaration for one unqualified database table."""
        return next(
            (
                resource
                for resource in self.resources
                if resource.kind is SessionLifecycleResourceKind.DATABASE_TABLE
                and resource.name == table_name
            ),
            None,
        )
