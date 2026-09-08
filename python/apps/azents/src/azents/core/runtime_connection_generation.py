"""Runtime connection-generation representation boundaries."""

MAX_RUNTIME_CONNECTION_GENERATION = 2**63 - 1
REDIS_RUNTIME_CONNECTION_GENERATION_WIDTH = 19
_MAX_REDIS_RUNTIME_CONNECTION_GENERATION = str(MAX_RUNTIME_CONNECTION_GENERATION)


def validate_runtime_connection_generation(generation: int) -> None:
    """Require one positive signed-BIGINT connection generation."""
    if not 1 <= generation <= MAX_RUNTIME_CONNECTION_GENERATION:
        raise ValueError(
            "Runtime connection generation must be a positive signed BIGINT"
        )


def runtime_connection_generation_to_redis(generation: int) -> str:
    """Encode a connection generation as one fixed-width Redis string."""
    validate_runtime_connection_generation(generation)
    return f"{generation:0{REDIS_RUNTIME_CONNECTION_GENERATION_WIDTH}d}"


def runtime_connection_generation_from_redis(value: object) -> int:
    """Decode one canonical fixed-width Redis connection generation."""
    if (
        not isinstance(value, str)
        or len(value) != REDIS_RUNTIME_CONNECTION_GENERATION_WIDTH
        or not value.isascii()
        or not value.isdigit()
        or value > _MAX_REDIS_RUNTIME_CONNECTION_GENERATION
    ):
        raise ValueError("Redis Runtime connection generation is not canonical")
    generation = int(value)
    validate_runtime_connection_generation(generation)
    return generation


def runtime_connection_generation_to_public(generation: int) -> str:
    """Encode one canonical public JSON connection generation."""
    validate_runtime_connection_generation(generation)
    return str(generation)


def runtime_connection_generation_from_public(value: object) -> int:
    """Decode one canonical public JSON connection generation."""
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or not value.isdigit()
        or (len(value) > 1 and value.startswith("0"))
    ):
        raise ValueError("Public Runtime connection generation is not canonical")
    generation = int(value)
    validate_runtime_connection_generation(generation)
    return generation
