"""Baseline contracts for the Agent deletion composition and installed schema."""

import dataclasses

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_deletion import AgentDeletionRegistry
from azents.core.agent_deletion_registry import get_agent_deletion_registry
from azents.core.agent_deletion_schema import validate_agent_deletion_schema
from azents.rdb.session_capabilities import create_read_only_session_manager
from azents.repos.session_lifecycle_schema import (
    PostgreSQLSessionLifecycleGraphRepository,
)


def test_registry_orders_dependencies_and_rejects_incomplete_handlers() -> None:
    registry = get_agent_deletion_registry()
    rebuilt = AgentDeletionRegistry(reversed(registry.participants))
    assert rebuilt.participants == registry.participants
    with pytest.raises(ValueError, match="handlers"):
        registry.require_handlers(item.key for item in registry.participants[:-1])
    registry.require_handlers(item.key for item in registry.participants)


def test_registry_rejects_duplicate_resource_owners() -> None:
    definitions = get_agent_deletion_registry().participants
    duplicate = dataclasses.replace(definitions[0], key="another.owner")
    with pytest.raises(ValueError, match="Duplicate Agent deletion ownership"):
        AgentDeletionRegistry((*definitions, duplicate))


@pytest.mark.parametrize("invalid", ["duplicate", "unknown", "cycle", "empty", "long"])
def test_registry_rejects_invalid_dependency_composition(invalid: str) -> None:
    definitions = list(get_agent_deletion_registry().participants)
    if invalid == "duplicate":
        definitions.append(definitions[0])
    elif invalid == "unknown":
        definitions[0] = dataclasses.replace(definitions[0], dependencies=("unknown",))
    elif invalid == "cycle":
        definitions[0] = dataclasses.replace(
            definitions[0], dependencies=(definitions[-1].key,)
        )
    else:
        definitions[0] = dataclasses.replace(
            definitions[0], key="" if invalid == "empty" else "x" * 81
        )
    with pytest.raises(ValueError):
        AgentDeletionRegistry(definitions)


@pytest.mark.parametrize("resource_kind", ["external", "historical"])
def test_registry_rejects_duplicate_non_fk_resources(resource_kind: str) -> None:
    definitions = list(get_agent_deletion_registry().participants)
    if resource_kind == "external":
        definitions[0] = dataclasses.replace(
            definitions[0], external_resources=("same-object", "same-object")
        )
    else:
        definitions[0] = dataclasses.replace(
            definitions[0], historical_resources=("same-history", "same-history")
        )
    with pytest.raises(ValueError, match="Duplicate Agent deletion resource"):
        AgentDeletionRegistry(definitions)


@pytest.mark.parametrize("columns", [(), ("agent_id", "workspace_id")])
def test_registry_rejects_incomplete_composite_identity(
    columns: tuple[str, ...],
) -> None:
    definitions = list(get_agent_deletion_registry().participants)
    first = definitions[0]
    definitions[0] = dataclasses.replace(
        first,
        relationships=(
            dataclasses.replace(first.relationships[0], source_columns=columns),
            *first.relationships[1:],
        ),
    )
    with pytest.raises(ValueError, match="Invalid Agent deletion relationship"):
        AgentDeletionRegistry(definitions)


async def test_installed_agent_deletion_edges_match_scoped_ownership(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """All actual root/cascade incoming FKs have a deliberately declared owner."""
    keys = await PostgreSQLSessionLifecycleGraphRepository(
        create_read_only_session_manager(rdb_engine)
    ).read_foreign_keys()
    registry = get_agent_deletion_registry()
    validate_agent_deletion_schema(registry=registry, foreign_keys=keys).require_safe()
    composite = next(
        edge
        for edge in keys
        if edge.source_table == "public.personal_toolkit_agents"
        and edge.target_table == "public.agents"
    )
    assert composite.source_columns == ("agent_id", "workspace_id")
    assert composite.target_columns == ("id", "workspace_id")
    provenance = next(
        edge
        for edge in keys
        if edge.source_table == "public.exchange_files"
        and edge.source_columns == ("source_agent_id",)
    )
    injected = dataclasses.replace(
        provenance,
        constraint_name="new_unowned_fk",
        source_columns=("unowned_agent_id",),
    )
    result = validate_agent_deletion_schema(
        registry=registry, foreign_keys=(*keys, injected)
    )
    assert any("new_unowned_fk" in error for error in result.violations)
