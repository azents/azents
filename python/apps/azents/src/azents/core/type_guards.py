"""Runtime type guards for untyped boundary values."""

from typing import TypeGuard


def is_object_list(value: object) -> TypeGuard[list[object]]:
    """Return whether a value is a list with unconstrained item values."""
    return isinstance(value, list)


def is_string_list(value: object) -> TypeGuard[list[str]]:
    """Return whether a value is a list of strings."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def is_string_object_dict(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a value is a dictionary with string keys."""
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def is_string_object_dict_list(value: object) -> TypeGuard[list[dict[str, object]]]:
    """Return whether a value is a list of dictionaries with string keys."""
    return isinstance(value, list) and all(
        is_string_object_dict(item) for item in value
    )


def is_string_string_dict(value: object) -> TypeGuard[dict[str, str]]:
    """Return whether a value is a dictionary with string keys and values."""
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )
