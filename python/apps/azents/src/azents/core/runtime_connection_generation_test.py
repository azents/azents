"""Tests for Runtime connection-generation representation boundaries."""

import pytest

from azents.core.runtime_connection_generation import (
    MAX_RUNTIME_CONNECTION_GENERATION,
    runtime_connection_generation_from_public,
    runtime_connection_generation_from_redis,
    runtime_connection_generation_to_public,
    runtime_connection_generation_to_redis,
)


def test_connection_generation_round_trips_signed_bigint_maximum() -> None:
    """Redis and public encodings preserve the exact signed-BIGINT maximum."""
    generation = MAX_RUNTIME_CONNECTION_GENERATION

    redis_value = runtime_connection_generation_to_redis(generation)
    public_value = runtime_connection_generation_to_public(generation)

    assert redis_value == "9223372036854775807"
    assert public_value == "9223372036854775807"
    assert runtime_connection_generation_from_redis(redis_value) == generation
    assert runtime_connection_generation_from_public(public_value) == generation


@pytest.mark.parametrize(
    "generation",
    [0, -1, MAX_RUNTIME_CONNECTION_GENERATION + 1],
)
def test_connection_generation_encoders_reject_out_of_domain_values(
    generation: int,
) -> None:
    """Connection generations must remain in the positive signed-BIGINT domain."""
    with pytest.raises(ValueError, match="positive signed BIGINT"):
        runtime_connection_generation_to_redis(generation)
    with pytest.raises(ValueError, match="positive signed BIGINT"):
        runtime_connection_generation_to_public(generation)


@pytest.mark.parametrize(
    "value",
    [
        1,
        "1",
        "0000000000000000000",
        "00000000000000000000",
        "9223372036854775808",
    ],
)
def test_redis_connection_generation_decoder_requires_canonical_fixed_width(
    value: object,
) -> None:
    """Redis generation values reject numbers and noncanonical decimal strings."""
    with pytest.raises(ValueError):
        runtime_connection_generation_from_redis(value)


@pytest.mark.parametrize(
    "value",
    [1, "", "0", "01", "-1", "9223372036854775808"],
)
def test_public_connection_generation_decoder_requires_canonical_decimal_string(
    value: object,
) -> None:
    """Public generation values reject numbers, zero, padding, and overflow."""
    with pytest.raises(ValueError):
        runtime_connection_generation_from_public(value)
