"""Toolkit base runtime hook API tests."""

from dataclasses import fields
from typing import Any

from azents.core.tools import ResolveContext, Toolkit, ToolkitContext, TurnContext


class _DefaultToolkit(Toolkit[Any]):
    """Toolkit used to verify the default hooks() implementation."""


def test_toolkit_hooks_default_is_empty_mapping() -> None:
    """A Toolkit subclass should return an empty no-op mapping from hooks()."""
    toolkit = _DefaultToolkit()

    assert toolkit.hooks() == {}


def test_generic_toolkit_contexts_exclude_user_and_interface_carriers() -> None:
    """Generic Team execution contexts carry only workload authority."""
    forbidden = {
        "user_id",
        "session_type",
        "interface_type",
        "interface_channel_id",
    }

    for context_type in (ToolkitContext, ResolveContext, TurnContext):
        assert {field.name for field in fields(context_type)}.isdisjoint(forbidden)
