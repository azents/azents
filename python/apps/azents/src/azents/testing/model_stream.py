"""Model stream watchdog test factories."""

from typing import Literal

from azents.engine.model_stream import (
    AsyncioModelStreamClock,
    ModelStreamCallContext,
    ModelStreamCleanupRegistry,
    ModelStreamTimeoutPolicy,
    ModelStreamTimeoutPolicyResolver,
    ModelStreamWatchdog,
)


def make_test_model_stream_watchdog(
    *,
    policy: ModelStreamTimeoutPolicy | None = None,
) -> ModelStreamWatchdog:
    """Create a watchdog with long deterministic-test defaults."""
    effective_policy = policy or ModelStreamTimeoutPolicy(
        connect_timeout_seconds=15,
        parsed_event_idle_timeout_seconds=300,
        absolute_attempt_timeout_seconds=1_800,
    )
    clock = AsyncioModelStreamClock()
    return ModelStreamWatchdog(
        resolver=ModelStreamTimeoutPolicyResolver(
            default=effective_policy,
            provider_overrides=(),
            specific_overrides=(),
        ),
        cleanup_registry=ModelStreamCleanupRegistry(clock=clock),
        close_grace_seconds=5,
        clock=clock,
    )


def make_test_model_stream_context(
    *,
    call_kind: Literal["sampling", "compaction", "session_title"] = "sampling",
) -> ModelStreamCallContext:
    """Create safe context for adapter and shared Responses tests."""
    if call_kind not in {"sampling", "compaction", "session_title"}:
        raise ValueError("unsupported test model stream call kind")
    return ModelStreamCallContext(
        call_kind=call_kind,
        provider="test",
        provider_integration_id=None,
        model="test-model",
        session_id="session-test",
        run_id="run-test",
        attempt_number=1,
        check_stop=None,
    )
