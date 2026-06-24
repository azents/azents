"""Toolkit base runtime hook API tests."""

from typing import Any

from azents.core.tools import Toolkit


class _DefaultToolkit(Toolkit[Any]):
    """Toolkit used to verify the default hooks() implementation."""


def test_toolkit_hooks_default_is_empty_mapping() -> None:
    """A Toolkit subclass should return an empty no-op mapping from hooks()."""
    toolkit = _DefaultToolkit()

    assert toolkit.hooks() == {}
