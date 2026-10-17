"""Read-only production schema evidence with test-local mutable copies."""

import copy
from typing import Any

import pytest

from azents.app import create_dummy_public_app


@pytest.fixture(scope="session")
def _full_public_openapi_source() -> dict[str, Any]:
    """Compile the complete actual production graph without retaining its app."""
    return create_dummy_public_app().openapi()


@pytest.fixture
def full_public_openapi(
    _full_public_openapi_source: dict[str, Any],
) -> dict[str, Any]:
    """Give each pure schema assertion an independent deep copy of the evidence."""
    return copy.deepcopy(_full_public_openapi_source)
