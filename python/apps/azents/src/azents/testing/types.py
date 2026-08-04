"""Type narrowing helpers for tests."""

from collections.abc import Callable
from typing import TypeGuard


def is_object_factory(value: object) -> TypeGuard[Callable[..., object]]:
    """Return whether a value is callable as an object factory."""
    return callable(value)


def is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a value is a dictionary with string keys."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)
