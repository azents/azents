"""Runtime Web transport contract tests."""

from datetime import UTC, datetime, timedelta

from azents_runtime_control.runner_web import RunnerWebIdentity


def test_approval_authority_may_outlive_one_transport() -> None:
    """Allow a finite request transport inside a longer approval cycle."""
    now = datetime(2026, 9, 12, tzinfo=UTC)

    identity = RunnerWebIdentity(
        tunnel_id="tunnel",
        endpoint_id="endpoint",
        cycle_id="cycle",
        endpoint_authority_revision=1,
        close_barrier=0,
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
        port=8765,
        join_nonce="nonce",
        registration_deadline_at=now + timedelta(seconds=10),
        approval_deadline_at=now + timedelta(minutes=30),
        transport_deadline_at=now + timedelta(minutes=10),
    )

    assert identity.approval_deadline_at > identity.transport_deadline_at
