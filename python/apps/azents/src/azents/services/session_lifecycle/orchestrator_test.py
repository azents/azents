"""Session lifecycle transition orchestration tests."""

import pytest

from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgePolicy,
    SessionLifecycleRegistry,
    SessionLifecycleTransitionContext,
    SessionLifecycleTransitionPolicy,
)
from azents.services.session_lifecycle.orchestrator import (
    SessionLifecycleOrchestrator,
)


def _participant(
    key: str,
    *,
    dependencies: tuple[str, ...] = (),
    archive_policy: SessionLifecycleTransitionPolicy,
    restore_policy: SessionLifecycleTransitionPolicy,
) -> SessionLifecycleParticipantDefinition:
    """Build a lifecycle participant definition for orchestration tests."""
    return SessionLifecycleParticipantDefinition(
        key=key,
        policy_version=1,
        dependencies=dependencies,
        owned_resources=(),
        archive_policy=archive_policy,
        restore_policy=restore_policy,
        purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
    )


def _orchestrator() -> SessionLifecycleOrchestrator:
    """Build a registry with each archive and restore dispatch mode."""
    return SessionLifecycleOrchestrator(
        registry=SessionLifecycleRegistry(
            (
                _participant(
                    "execution",
                    archive_policy=SessionLifecycleTransitionPolicy.VALIDATE,
                    restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                ),
                _participant(
                    "external-channel",
                    dependencies=("execution",),
                    archive_policy=SessionLifecycleTransitionPolicy.TERMINATE,
                    restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                ),
                _participant(
                    "reversible",
                    dependencies=("external-channel",),
                    archive_policy=SessionLifecycleTransitionPolicy.MUTATE,
                    restore_policy=SessionLifecycleTransitionPolicy.MUTATE,
                ),
                _participant(
                    "files",
                    archive_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                    restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
                ),
            )
        )
    )


def _context() -> SessionLifecycleTransitionContext:
    """Build a valid locked root-tree transition context."""
    return SessionLifecycleTransitionContext(
        transition_id="transition-1",
        root_session_id="root-1",
        subtree_session_ids=("root-1", "child-1"),
    )


@pytest.mark.asyncio
async def test_archive_dispatches_participants_before_root_transition() -> None:
    """Archive applies validation, mutation, and termination in registry order."""
    events: list[str] = []

    async def participant_operation(
        participant: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        assert context == _context()
        events.append(f"participant:{participant.key}")

    async def transition() -> None:
        events.append("root")

    await _orchestrator().archive(
        context=_context(),
        participant_operation=participant_operation,
        transition=transition,
    )

    assert events == [
        "participant:execution",
        "participant:external-channel",
        "participant:reversible",
        "root",
    ]


@pytest.mark.asyncio
async def test_restore_dispatches_participants_in_reverse_order() -> None:
    """Restore mutates reversible state and validates terminal preservation."""
    events: list[str] = []

    async def participant_operation(
        participant: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        assert context == _context()
        if participant.key == "external-channel":
            assert (
                participant.restore_policy is SessionLifecycleTransitionPolicy.PRESERVE
            )
            events.append("validate-preserved:external-channel")
            return
        events.append(f"participant:{participant.key}")

    async def transition() -> None:
        events.append("root")

    await _orchestrator().restore(
        context=_context(),
        participant_operation=participant_operation,
        transition=transition,
    )

    assert events == [
        "participant:reversible",
        "validate-preserved:external-channel",
        "root",
    ]


@pytest.mark.asyncio
async def test_archive_propagates_participant_failure_before_root_transition() -> None:
    """A caller transaction can roll back when a participant operation fails."""
    events: list[str] = []

    async def participant_operation(
        participant: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        del context
        events.append(f"participant:{participant.key}")
        if participant.key == "external-channel":
            raise RuntimeError("termination failed")

    async def transition() -> None:
        events.append("root")

    with pytest.raises(RuntimeError, match="termination failed"):
        await _orchestrator().archive(
            context=_context(),
            participant_operation=participant_operation,
            transition=transition,
        )

    assert events == [
        "participant:execution",
        "participant:external-channel",
    ]
