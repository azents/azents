"""Provider-tool activity normalization tests."""

from azents.engine.events.protocols import ProviderToolActivityProjection
from azents.engine.events.provider_tool_activity import (
    ProviderToolActivityAccumulator,
    ProviderToolObservation,
)


def test_emits_first_observation_and_suppresses_exact_duplicate() -> None:
    """Emit only when the canonical public snapshot changes."""
    accumulator = ProviderToolActivityAccumulator()
    observation = ProviderToolObservation(
        call_id="call-1",
        name="web_search",
        status="running",
    )

    assert accumulator.observe(observation) == ProviderToolActivityProjection(
        call_id="call-1",
        name="web_search",
        status="running",
        arguments=None,
    )
    assert accumulator.observe(observation) is None


def test_enriches_arguments_and_keeps_terminal_state_monotonic() -> None:
    """Retain later arguments without allowing terminal state regression."""
    accumulator = ProviderToolActivityAccumulator()
    accumulator.observe(
        ProviderToolObservation(
            call_id="call-1",
            name="web_search",
            status="running",
        )
    )
    assert accumulator.observe(
        ProviderToolObservation(
            call_id="call-1",
            name="web_search",
            status="completed",
        )
    ) == ProviderToolActivityProjection(
        call_id="call-1",
        name="web_search",
        status="completed",
        arguments=None,
    )
    assert accumulator.observe(
        ProviderToolObservation(
            call_id="call-1",
            name="web_search",
            status="running",
            arguments='{"query":"azents"}',
        )
    ) == ProviderToolActivityProjection(
        call_id="call-1",
        name="web_search",
        status="completed",
        arguments='{"query":"azents"}',
    )
    assert (
        accumulator.observe(
            ProviderToolObservation(
                call_id="call-1",
                name="web_search",
                status="failed",
                arguments='{"query":"azents"}',
            )
        )
        is None
    )


def test_tracks_multiple_calls_independently() -> None:
    """Keep independent snapshots for concurrent provider calls."""
    accumulator = ProviderToolActivityAccumulator()

    first = accumulator.observe(
        ProviderToolObservation(
            call_id="call-1",
            name="web_search",
            status="running",
        )
    )
    second = accumulator.observe(
        ProviderToolObservation(
            call_id="call-2",
            name="image_generation",
            status="running",
        )
    )

    assert first is not None
    assert first.call_id == "call-1"
    assert second is not None
    assert second.call_id == "call-2"
