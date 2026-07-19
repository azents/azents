"""Tests for deferred Tool Search and session working-set state."""

import datetime
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.engine.run.tool_budget import (
    ResolvedToolDeclarationBudget,
    ToolCompatibilityRuleSource,
    ToolDeclarationBudgetExceededError,
    ToolDeclarationCountingScope,
    ToolRequestCompatibilityRule,
)
from azents.engine.run.types import FunctionTool, FunctionToolSpec
from azents.engine.tooling.tool_search import (
    CatalogTool,
    DeferredToolSearchIndex,
    ToolCatalogSource,
    ToolExposure,
    ToolWorkingSetState,
    ToolWorkingSetStore,
    make_tool_search_tool,
    project_tool_catalog,
)
from azents.rdb.session import SessionManager
from azents.repos.toolkit_state import (
    ToolkitStateConflictError,
    ToolkitStateRepository,
)
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert


async def _handler(arguments: str) -> str:
    return arguments


def _entry(
    name: str,
    description: str,
    *,
    exposure: ToolExposure = ToolExposure.DEFERRED,
    slug: str = "azents",
    toolkit_type: str | None = "github",
    input_schema: dict[str, object] | None = None,
) -> CatalogTool:
    return CatalogTool(
        tool=FunctionTool(
            spec=FunctionToolSpec(
                name=name,
                description=description,
                input_schema=input_schema or {"type": "object", "properties": {}},
            ),
            handler=_handler,
        ),
        source=ToolCatalogSource(
            slug=slug,
            toolkit_type=toolkit_type,
            toolkit_class="TestToolkit",
            display_name="GitHub",
            use_prefix=True,
            routing_metadata=(("account", slug),),
        ),
        exposure=exposure,
    )


def _budget(client_capacity: int | None) -> ResolvedToolDeclarationBudget:
    if client_capacity is None:
        return ResolvedToolDeclarationBudget(
            rule=None,
            counted_provider_hosted_declarations=0,
            client_function_capacity=None,
        )
    rule = ToolRequestCompatibilityRule(
        rule_id="test-limit",
        registry_version=1,
        provider=LLMProvider.OPENAI,
        adapter="openai",
        native_format="responses",
        maximum_declarations=client_capacity,
        counting_scope=ToolDeclarationCountingScope.TOTAL_TOOLS,
        source=ToolCompatibilityRuleSource(
            urls=("https://example.com/tool-limit",),
            verified_on=datetime.date(2026, 7, 19),
            note=None,
        ),
    )
    return ResolvedToolDeclarationBudget(
        rule=rule,
        counted_provider_hosted_declarations=0,
        client_function_capacity=client_capacity,
    )


class _MemoryToolkitStateRepository(ToolkitStateRepository):
    """In-memory Toolkit State repository with one optional CAS conflict."""

    def __init__(self) -> None:
        self.record: ToolkitStateRecord | None = None
        self.conflict_next_update = False

    async def get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        toolkit_namespace: str,
        state_name: str,
    ) -> ToolkitStateRecord | None:
        del session, agent_id, session_id, toolkit_namespace, state_name
        return self.record

    async def save(
        self,
        session: AsyncSession,
        state: ToolkitStateUpsert,
    ) -> ToolkitStateRecord:
        del session
        if self.record is None:
            if state.expected_version is not None:
                raise ToolkitStateConflictError("missing state")
            self.record = _record(state, version=1)
            return self.record
        if state.expected_version != self.record.version:
            raise ToolkitStateConflictError("version conflict")
        if self.conflict_next_update:
            self.conflict_next_update = False
            self.record = self.record.model_copy(
                update={
                    "state_json": {
                        "schema_version": 1,
                        "tool_names": ["concurrent", "old"],
                    },
                    "version": self.record.version + 1,
                }
            )
            raise ToolkitStateConflictError("simulated conflict")
        self.record = _record(state, version=self.record.version + 1)
        return self.record


def _record(state: ToolkitStateUpsert, *, version: int) -> ToolkitStateRecord:
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitStateRecord(
        id="state-1",
        agent_id=state.agent_id,
        session_id=state.session_id,
        toolkit_namespace=state.toolkit_namespace,
        state_name=state.state_name,
        state_json=state.state_json,
        schema_version=state.schema_version,
        version=version,
        created_at=now,
        updated_at=now,
    )


@asynccontextmanager
async def _session_manager() -> AsyncIterator[AsyncSession]:
    async with AsyncSession() as session:
        yield session


def _working_set_store(
    repository: ToolkitStateRepository,
) -> ToolWorkingSetStore:
    session_manager: SessionManager[AsyncSession] = _session_manager
    return ToolWorkingSetStore(
        session_manager=session_manager,
        repository=repository,
    )


def test_search_ranks_name_description_and_source_metadata() -> None:
    index = DeferredToolSearchIndex(
        [
            _entry(
                "github__create_issue",
                "Create a repository issue.",
                slug="azents",
            ),
            _entry(
                "notion__search_pages",
                "Search workspace pages.",
                slug="docs",
                toolkit_type="notion",
            ),
        ]
    )

    issue_matches = index.search("create repository issue", limit=5)
    source_matches = index.search("azents account", limit=5)

    assert [match.name for match in issue_matches] == ["github__create_issue"]
    assert source_matches[0].name == "github__create_issue"


def test_search_indexes_parameter_names_and_descriptions() -> None:
    index = DeferredToolSearchIndex(
        [
            _entry(
                "github__create_issue",
                "Create an item.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "repo": {
                            "type": "string",
                            "description": "Repository name",
                        }
                    },
                },
            )
        ]
    )

    matches = index.search("repository", limit=5)

    assert [match.name for match in matches] == ["github__create_issue"]


def test_search_uses_final_name_for_deterministic_ties() -> None:
    index = DeferredToolSearchIndex(
        [
            _entry("service__beta", "Shared capability."),
            _entry("service__alpha", "Shared capability."),
        ]
    )

    matches = index.search("shared capability", limit=5)

    assert [match.name for match in matches] == [
        "service__alpha",
        "service__beta",
    ]


def test_search_excludes_direct_tools_and_handles_empty_query() -> None:
    index = DeferredToolSearchIndex(
        [
            _entry(
                "exec_command",
                "Run a shell command.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
            _entry("github__create_issue", "Create an issue."),
        ]
    )

    assert index.search("shell command", limit=5) == []
    assert index.search("", limit=5) == []


def test_search_rejects_result_limit_above_maximum() -> None:
    index = DeferredToolSearchIndex([_entry("service__tool", "Use service.")])

    with pytest.raises(ValueError, match="between 1 and 10"):
        index.search("service", limit=11)


def test_catalog_hash_changes_with_searchable_metadata() -> None:
    original = DeferredToolSearchIndex(
        [_entry("github__create_issue", "Create an issue.")]
    )
    changed_description = DeferredToolSearchIndex(
        [_entry("github__create_issue", "Open an issue.")]
    )
    changed_schema = DeferredToolSearchIndex(
        [
            _entry(
                "github__create_issue",
                "Create an issue.",
                input_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            )
        ]
    )

    assert original.catalog_hash != changed_description.catalog_hash
    assert original.catalog_hash != changed_schema.catalog_hash


def test_projection_uses_mru_membership_and_canonical_provider_order() -> None:
    entries = {
        entry.tool.spec.name: entry
        for entry in [
            _entry(
                "exec_command",
                "Run a command.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
            _entry(
                "tool_search",
                "Search tools.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
            _entry("service__alpha", "Alpha operation."),
            _entry("service__beta", "Beta operation."),
            _entry("service__gamma", "Gamma operation."),
        ]
    }
    state = ToolWorkingSetState(
        tool_names=["service__gamma", "missing", "service__alpha", "service__beta"]
    )

    projection = project_tool_catalog(
        entries=entries,
        working_set=state,
        budget=_budget(3),
    )

    assert projection.direct_tool_names == ("exec_command", "tool_search")
    assert projection.active_deferred_tool_names == (
        "service__gamma",
        "service__alpha",
        "service__beta",
    )
    assert projection.visible_deferred_tool_names == ("service__gamma",)
    assert projection.provider_visible_tool_names == (
        "exec_command",
        "service__gamma",
        "tool_search",
    )
    assert projection.deferred_capacity == 1
    assert state.tool_names[1] == "missing"


def test_unlimited_projection_exposes_all_available_active_tools() -> None:
    entries = {
        entry.tool.spec.name: entry
        for entry in [
            _entry(
                "exec_command",
                "Run a command.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
            _entry("service__alpha", "Alpha operation."),
            _entry("service__beta", "Beta operation."),
        ]
    }

    projection = project_tool_catalog(
        entries=entries,
        working_set=ToolWorkingSetState(
            tool_names=["service__beta", "missing", "service__alpha"]
        ),
        budget=_budget(None),
    )

    assert projection.visible_deferred_tool_names == (
        "service__beta",
        "service__alpha",
    )
    assert projection.provider_visible_tool_names == (
        "exec_command",
        "service__alpha",
        "service__beta",
    )
    assert projection.deferred_capacity is None


def test_projection_rejects_direct_tool_overflow() -> None:
    entries = {
        entry.tool.spec.name: entry
        for entry in [
            _entry(
                "exec_command",
                "Run a command.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
            _entry(
                "tool_search",
                "Search tools.",
                exposure=ToolExposure.DIRECT,
                toolkit_type=None,
            ),
        ]
    }

    with pytest.raises(ToolDeclarationBudgetExceededError):
        project_tool_catalog(
            entries=entries,
            working_set=ToolWorkingSetState(),
            budget=_budget(1),
        )


async def test_working_set_activation_and_touch_preserve_mru_order() -> None:
    repository = _MemoryToolkitStateRepository()
    store = _working_set_store(repository)

    await store.activate("agent-1", "session-1", ["beta", "alpha", "beta"])
    activated = await store.activate(
        "agent-1",
        "session-1",
        ["alpha", "gamma"],
    )
    touched = await store.touch("agent-1", "session-1", "beta")

    assert activated.tool_names == ["alpha", "gamma", "beta"]
    assert touched.tool_names == ["beta", "alpha", "gamma"]


async def test_working_set_retry_reapplies_touch_to_concurrent_state() -> None:
    repository = _MemoryToolkitStateRepository()
    store = _working_set_store(repository)
    await store.activate("agent-1", "session-1", ["old"])
    repository.conflict_next_update = True

    touched = await store.touch("agent-1", "session-1", "target")

    assert touched.tool_names == ["target", "concurrent", "old"]


async def test_tool_search_reports_explicit_capacity_reduction() -> None:
    repository = _MemoryToolkitStateRepository()
    store = _working_set_store(repository)
    index = DeferredToolSearchIndex(
        [
            _entry("github__create_issue", "Create a repository issue."),
            _entry("github__list_issues", "List repository issues."),
        ]
    )
    tool = make_tool_search_tool(
        index=index,
        store=store,
        agent_id="agent-1",
        session_id="session-1",
        activation_capacity=1,
    )

    output = await tool.handler('{"query":"repository issue","limit":5}')
    state = await store.load("agent-1", "session-1")

    assert isinstance(output, str)
    payload = json.loads(output)
    assert payload["limit_reduced"] is True
    assert payload["activation_limit"] == 1
    assert len(payload["activated_tools"]) == 1
    assert len(state.tool_names) == 1


async def test_tool_search_schema_and_handler_activate_ranked_results() -> None:
    repository = _MemoryToolkitStateRepository()
    store = _working_set_store(repository)
    index = DeferredToolSearchIndex(
        [
            _entry("github__create_issue", "Create a repository issue."),
            _entry("github__list_issues", "List repository issues."),
        ]
    )
    tool = make_tool_search_tool(
        index=index,
        store=store,
        agent_id="agent-1",
        session_id="session-1",
        activation_capacity=None,
    )

    output = await tool.handler('{"query":"create issue"}')
    state = await store.load("agent-1", "session-1")

    assert isinstance(output, str)
    payload = json.loads(output)
    assert payload["activated_tools"][0]["name"] == "github__create_issue"
    assert state.tool_names[0] == "github__create_issue"
    assert tool.spec.name == "tool_search"
    properties = tool.spec.input_schema["properties"]
    assert isinstance(properties, dict)
    limit_schema = properties["limit"]
    assert isinstance(limit_schema, dict)
    assert limit_schema["default"] == 5
    assert limit_schema["maximum"] == 10
