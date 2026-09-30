"""Bounded ordinary watchdog policy for explicit E2E response barriers."""


def ordinary_model_stream_environment() -> dict[str, str]:
    """Allow public-API coordination while keeping every attempt bounded."""
    return {
        "AZ_MODEL_STREAM_CONNECT_TIMEOUT_SECONDS": "15",
        "AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS": "30",
        "AZ_MODEL_STREAM_ABSOLUTE_TIMEOUT_SECONDS": "120",
        "AZ_MODEL_STREAM_CLOSE_GRACE_SECONDS": "1",
    }
