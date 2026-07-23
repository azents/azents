"""Session lifecycle registry contract tests."""

import pytest

from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecycleParticipantVersionUnsupported,
    SessionLifecyclePurgePolicy,
    SessionLifecycleRegistry,
    SessionLifecycleResource,
    SessionLifecycleResourceClassification,
    SessionLifecycleResourceKind,
    SessionLifecycleTransitionPolicy,
)
from azents.services.session_lifecycle.registry import get_session_lifecycle_registry


def _participant(
    key: str,
    *,
    dependencies: tuple[str, ...] = (),
    resource_name: str | None = None,
    archive_policy: SessionLifecycleTransitionPolicy = (
        SessionLifecycleTransitionPolicy.PRESERVE
    ),
    restore_policy: SessionLifecycleTransitionPolicy = (
        SessionLifecycleTransitionPolicy.PRESERVE
    ),
) -> SessionLifecycleParticipantDefinition:
    """Build one concise registry test participant."""
    return SessionLifecycleParticipantDefinition(
        key=key,
        policy_version=1,
        dependencies=dependencies,
        owned_resources=()
        if resource_name is None
        else (
            SessionLifecycleResource(
                kind=SessionLifecycleResourceKind.DATABASE_TABLE,
                name=resource_name,
                classification=SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
                test_node_id="test_session_lifecycle_registry",
            ),
        ),
        archive_policy=archive_policy,
        restore_policy=restore_policy,
        purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
    )


def test_registry_order_is_deterministic_and_respects_dependencies() -> None:
    """Independent registration order cannot change the compiled dependency order."""
    registry = SessionLifecycleRegistry(
        (
            _participant("context", dependencies=("worktree",)),
            _participant("broker", dependencies=("execution",)),
            _participant("worktree"),
            _participant("execution"),
        )
    )

    assert [participant.key for participant in registry.participants] == [
        "execution",
        "worktree",
        "broker",
        "context",
    ]


@pytest.mark.parametrize(
    ("participants", "error"),
    (
        (
            (_participant("duplicate"), _participant("duplicate")),
            "Duplicate session lifecycle participant key",
        ),
        (
            (_participant("missing", dependencies=("not-registered",)),),
            "dependency is not registered",
        ),
        (
            (
                _participant("first", dependencies=("second",)),
                _participant("second", dependencies=("first",)),
            ),
            "dependency cycle",
        ),
        (
            (
                _participant("first", resource_name="owned_rows"),
                _participant("second", resource_name="owned_rows"),
            ),
            "Overlapping session lifecycle resource ownership",
        ),
    ),
)
def test_registry_rejects_invalid_participant_definitions(
    participants: tuple[SessionLifecycleParticipantDefinition, ...],
    error: str,
) -> None:
    """Invalid keys, dependencies, and ownership declarations fail at composition."""
    with pytest.raises(ValueError, match=error):
        SessionLifecycleRegistry(participants)


@pytest.mark.parametrize(
    ("archive_policy", "restore_policy"),
    (
        (
            SessionLifecycleTransitionPolicy.MUTATE,
            SessionLifecycleTransitionPolicy.PRESERVE,
        ),
        (
            SessionLifecycleTransitionPolicy.PRESERVE,
            SessionLifecycleTransitionPolicy.MUTATE,
        ),
        (
            SessionLifecycleTransitionPolicy.TERMINATE,
            SessionLifecycleTransitionPolicy.MUTATE,
        ),
        (
            SessionLifecycleTransitionPolicy.TERMINATE,
            SessionLifecycleTransitionPolicy.VALIDATE,
        ),
        (
            SessionLifecycleTransitionPolicy.PRESERVE,
            SessionLifecycleTransitionPolicy.TERMINATE,
        ),
        (
            SessionLifecycleTransitionPolicy.PRESERVE,
            SessionLifecycleTransitionPolicy.VALIDATE,
        ),
    ),
)
def test_registry_rejects_unsupported_asymmetric_transition_policies(
    archive_policy: SessionLifecycleTransitionPolicy,
    restore_policy: SessionLifecycleTransitionPolicy,
) -> None:
    """Only declared validation and terminal preservation asymmetry is valid."""
    with pytest.raises(ValueError):
        SessionLifecycleRegistry(
            (
                _participant(
                    "asymmetric",
                    archive_policy=archive_policy,
                    restore_policy=restore_policy,
                ),
            )
        )


@pytest.mark.parametrize(
    ("archive_policy", "restore_policy"),
    (
        (
            SessionLifecycleTransitionPolicy.PRESERVE,
            SessionLifecycleTransitionPolicy.PRESERVE,
        ),
        (
            SessionLifecycleTransitionPolicy.VALIDATE,
            SessionLifecycleTransitionPolicy.PRESERVE,
        ),
        (
            SessionLifecycleTransitionPolicy.VALIDATE,
            SessionLifecycleTransitionPolicy.VALIDATE,
        ),
        (
            SessionLifecycleTransitionPolicy.MUTATE,
            SessionLifecycleTransitionPolicy.MUTATE,
        ),
        (
            SessionLifecycleTransitionPolicy.TERMINATE,
            SessionLifecycleTransitionPolicy.PRESERVE,
        ),
    ),
)
def test_registry_accepts_supported_transition_policies(
    archive_policy: SessionLifecycleTransitionPolicy,
    restore_policy: SessionLifecycleTransitionPolicy,
) -> None:
    """Transition policy pairs encode only intentional lifecycle behavior."""
    registry = SessionLifecycleRegistry(
        (
            _participant(
                "supported",
                archive_policy=archive_policy,
                restore_policy=restore_policy,
            ),
        )
    )

    assert registry.get("supported").archive_policy is archive_policy
    assert registry.get("supported").restore_policy is restore_policy


def test_external_channel_participant_declares_session_owned_foundation_state() -> None:
    """External Channel foundation state is lifecycle-classified before activation."""
    participant = get_session_lifecycle_registry().get("session.external-channel")

    assert participant.policy_version == 1
    assert participant.dependencies == ("session.execution",)
    assert participant.archive_policy is SessionLifecycleTransitionPolicy.TERMINATE
    assert participant.restore_policy is SessionLifecycleTransitionPolicy.PRESERVE
    assert participant.purge_policy is SessionLifecyclePurgePolicy.REQUIRED
    assert {
        (resource.name, resource.classification)
        for resource in participant.owned_resources
    } == {
        (
            "external_channel_bindings",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_invocation_batches",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_invocation_batch_items",
            SessionLifecycleResourceClassification.PURE_DATABASE_CHILD,
        ),
        (
            "external_channel_access_requests",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_access_grants",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_works",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_actions",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
        (
            "external_channel_delivery_attempts",
            SessionLifecycleResourceClassification.LIFECYCLE_ROOT,
        ),
    }


def test_registry_rejects_unavailable_persisted_policy_version() -> None:
    """A fenced job cannot silently switch to a new participant contract."""
    registry = get_session_lifecycle_registry()

    with pytest.raises(SessionLifecycleParticipantVersionUnsupported):
        registry.require_policy_version(
            key="session.model-files",
            policy_version=2,
        )
