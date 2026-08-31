"""Type narrowing helpers for tests."""

from collections.abc import Callable
from typing import TypeGuard, TypeVar

T = TypeVar("T")


def is_object_factory(value: object) -> TypeGuard[Callable[..., object]]:
    """Return whether a value is callable as an object factory."""
    return callable(value)


def is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a value is a dictionary with string keys."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def is_object_list(value: object) -> TypeGuard[list[object]]:
    """Return whether a value is a list with an unconstrained item type."""
    return isinstance(value, list)


def require_instance(value: object, expected: type[T]) -> T:
    """Return a runtime-validated typed test value."""
    if not isinstance(value, expected):
        raise AssertionError(
            f"Expected {expected.__name__}, got {type(value).__name__}."
        )
    return value
