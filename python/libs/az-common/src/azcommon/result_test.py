"""Result discriminator regression tests."""

import dataclasses
from typing import assert_never

from .result import Failure, Result, Success


@dataclasses.dataclass(frozen=True)
class _FirstFailure:
    """First closed failure variant."""


@dataclasses.dataclass(frozen=True)
class _SecondFailure:
    """Second closed failure variant."""


def _consume_result(
    result: Result[int, _FirstFailure | _SecondFailure],
) -> str:
    """Consume a Result through its literal success discriminator."""
    if result.success:
        return f"success:{result.value}"

    error = result.error
    match error:
        case _FirstFailure():
            return "first_failure"
        case _SecondFailure():
            return "second_failure"
        case _:
            assert_never(error)


def test_success_discriminator_preserves_failure_exhaustiveness() -> None:
    """Result consumers retain exact Success and Failure handling."""
    assert _consume_result(Success(7)) == "success:7"
    assert _consume_result(Failure(_FirstFailure())) == "first_failure"
    assert _consume_result(Failure(_SecondFailure())) == "second_failure"
