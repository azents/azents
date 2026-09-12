"""Execution authority binding contract tests."""

import pytest

from azents.services.session_resource_authority import (
    SessionExecutionOwner,
    SessionResourceAuthority,
    accepts_execution_authority,
    accepts_execution_owner,
)


def _authority(
    *, run_id: str, run_index: int, generation: int = 3
) -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace",
        agent_id="agent",
        session_id="session",
        root_session_id="session",
        run_id=run_id,
        run_index=run_index,
        owner_generation=generation,
    )


def test_full_authority_refreshes_across_runs_for_same_session_owner() -> None:
    """Run-specific authority may refresh while durable ownership stays unchanged."""
    first = _authority(run_id="run-1", run_index=1)
    second = _authority(run_id="run-2", run_index=2)

    assert accepts_execution_authority(
        None,
        first,
        agent_id="agent",
        session_id="session",
    )
    assert accepts_execution_authority(
        first,
        second,
        agent_id="agent",
        session_id="session",
    )
    assert not accepts_execution_authority(
        second,
        second,
        agent_id="agent",
        session_id="session",
    )


def test_execution_owner_rejects_takeover_on_reused_toolkit() -> None:
    """A Toolkit instance cannot cross a durable owner-generation boundary."""
    current = SessionExecutionOwner(session_id="session", owner_generation=3)

    assert accepts_execution_owner(None, current, session_id="session")
    assert not accepts_execution_owner(current, current, session_id="session")
    with pytest.raises(ValueError, match="another execution owner"):
        accepts_execution_owner(
            current,
            SessionExecutionOwner(session_id="session", owner_generation=4),
            session_id="session",
        )


def test_full_authority_rejects_identity_mismatch() -> None:
    """Full resource binding validates captured Agent and Session identity."""
    authority = _authority(run_id="run-1", run_index=1)

    with pytest.raises(ValueError, match="Agent"):
        accepts_execution_authority(
            None,
            authority,
            agent_id="other-agent",
            session_id="session",
        )
    with pytest.raises(ValueError, match="Session"):
        accepts_execution_authority(
            None,
            authority,
            agent_id="agent",
            session_id="other-session",
        )
