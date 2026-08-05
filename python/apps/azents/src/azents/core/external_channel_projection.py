"""Typed decoding helpers for bounded durable provider projections."""

from typing import TypeGuard

type ExternalChannelProjection = dict[str, object]


def is_external_channel_projection(
    value: object,
) -> TypeGuard[ExternalChannelProjection]:
    """Return whether a value is a JSON-object-shaped provider projection."""
    if not isinstance(value, dict):
        return False
    return all(isinstance(key, str) for key in value)


def is_external_channel_projection_list(
    value: object,
) -> TypeGuard[list[ExternalChannelProjection]]:
    """Return whether a value is a bounded list of provider projections."""
    return isinstance(value, list) and all(
        is_external_channel_projection(item) for item in value
    )
