"""Shared Toolkit identifier conformance tests."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from azents.core.toolkit_identifiers import (
    IdentifierValidationError,
    normalize_explicit_toolkit_slug,
    resolve_default_toolkit_slug,
    resolve_toolkit_name,
    slugify_toolkit_name,
)
from azents.engine.tools.deps import get_toolkit_registry
from azents.repos.engine_runtime_tool_read import EngineRuntimeToolReadRepository
from azents.repos.engine_tool_repositories import (
    EngineMcpSnapshotFactory,
    EngineToolRepositories,
)
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)
from azents.repos.memory.operations import MemoryOperationRepository
from azents.repos.toolkit_state.engine import ToolkitAgentsAppendixDedupeStateStore
from azents.testing.types import require_instance

_CORPUS_PATH = (
    Path(__file__).parents[7] / "testdata" / "toolkit_identifier_conformance_v1.json"
)


@pytest.fixture(scope="module")
def corpus() -> dict[str, Any]:
    """Load the language-neutral identifier conformance corpus."""
    with _CORPUS_PATH.open(encoding="utf-8") as file:
        return json.load(file)


def test_name_conformance(corpus: dict[str, Any]) -> None:
    """Match every shared Name resolution vector."""
    for case in corpus["name_cases"]:
        result = resolve_toolkit_name(
            case["toolkit_type"],
            case["canonical_name"],
            case["submitted"],
        )
        if "error_field" in case:
            assert isinstance(result, IdentifierValidationError), case["id"]
            assert result.field == case["error_field"], case["id"]
        else:
            assert result == case["expected"], case["id"]


def test_default_slug_conformance(corpus: dict[str, Any]) -> None:
    """Match every shared default Slug vector."""
    for case in corpus["default_slug_cases"]:
        assert (
            resolve_default_toolkit_slug(
                case["effective_name"],
                case["canonical_name"],
            )
            == case["expected"]
        ), case["id"]


def test_explicit_slug_conformance(corpus: dict[str, Any]) -> None:
    """Match every shared explicit Slug normalization vector."""
    for case in corpus["explicit_slug_cases"]:
        result = normalize_explicit_toolkit_slug(case["submitted"])
        if "error_field" in case:
            assert isinstance(result, IdentifierValidationError), case["id"]
            assert result.field == case["error_field"], case["id"]
        elif case.get("reset"):
            assert result is None, case["id"]
        else:
            assert result == case["expected"], case["id"]


def test_registered_provider_names_produce_fallback_slugs() -> None:
    """Require every configurable Provider Name to satisfy the fallback invariant."""
    registry = get_toolkit_registry(
        EngineToolRepositories(
            memory=require_instance(
                MagicMock(spec=MemoryOperationRepository), MemoryOperationRepository
            ),
            runtime=require_instance(
                MagicMock(spec=EngineRuntimeToolReadRepository),
                EngineRuntimeToolReadRepository,
            ),
            mcp_oauth=require_instance(
                MagicMock(spec=MCPOAuthRuntimeOperationRepository),
                MCPOAuthRuntimeOperationRepository,
            ),
            snapshots=require_instance(
                MagicMock(spec=EngineMcpSnapshotFactory), EngineMcpSnapshotFactory
            ),
            appendix=require_instance(
                MagicMock(spec=ToolkitAgentsAppendixDedupeStateStore),
                ToolkitAgentsAppendixDedupeStateStore,
            ),
        ),
        MagicMock(testenv_api_enabled=False),
        MagicMock(),
        MagicMock(),
    )

    assert registry
    assert all(slugify_toolkit_name(provider.name) for provider in registry.values())
