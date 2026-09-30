"""Offline contract checks for the explicit response-barrier worker policy."""

from support.model_stream_fixture_policy import ordinary_model_stream_environment


def test_barrier_policy_is_bounded_and_operation_specific() -> None:
    """Use ordinary attempt bounds without relying on time to release a barrier."""
    environment = ordinary_model_stream_environment()
    assert environment == {
        "AZ_MODEL_STREAM_CONNECT_TIMEOUT_SECONDS": "15",
        "AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS": "30",
        "AZ_MODEL_STREAM_ABSOLUTE_TIMEOUT_SECONDS": "120",
        "AZ_MODEL_STREAM_CLOSE_GRACE_SECONDS": "1",
    }
    assert all(float(value) > 0 for value in environment.values())


def test_barrier_policy_returns_independent_environment_mapping() -> None:
    """A caller cannot mutate the policy used by a later fixture invocation."""
    environment = ordinary_model_stream_environment()
    environment["AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS"] = "999"
    assert (
        ordinary_model_stream_environment()["AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS"]
        == "30"
    )
