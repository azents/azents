"""Deferred tool search and session-scoped working-set state."""

import dataclasses
import enum
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.run.tool_budget import (
    ResolvedToolDeclarationBudget,
    ensure_pinned_direct_tools_fit,
)
from azents.engine.run.types import FunctionTool
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tooling.toolkit_state import (
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.rdb.session import SessionManager
from azents.repos.toolkit_state import ToolkitStateRepository

TOOL_SEARCH_TOOLKIT_NAMESPACE = "tool_search"
TOOL_SEARCH_WORKING_SET_STATE_NAME = "working_set"
TOOL_SEARCH_STATE_SCHEMA_VERSION = 1
TOOL_SEARCH_DEFAULT_RESULT_LIMIT = 5
TOOL_SEARCH_MAX_RESULT_LIMIT = 10

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_BM25_K1 = 1.5
_BM25_B = 0.75
_DIRECT_REGISTERED_TOOLS = frozenset({("github", "switch_installation")})
_TOOL_SEARCH_DESCRIPTION = (
    "Search deferred tools by capability and activate matching tools for the next "
    "model call. Use a concise query describing the capability you need."
)


class ToolExposure(enum.StrEnum):
    """Whether a client function is pinned or discovered through Tool Search."""

    DIRECT = "direct"
    DEFERRED = "deferred"


@dataclasses.dataclass(frozen=True)
class ToolCatalogSource:
    """Toolkit source metadata retained for one executable tool."""

    slug: str
    toolkit_type: str | None
    toolkit_class: str
    display_name: str
    use_prefix: bool
    toolkit_config_id: str | None = None
    routing_metadata: tuple[tuple[str, str], ...] = ()

    @property
    def label(self) -> str:
        """Return the best human-readable source label."""
        return self.display_name or self.slug or self.toolkit_class


@dataclasses.dataclass(frozen=True)
class CatalogTool:
    """Executable function plus source and model-exposure policy."""

    tool: FunctionTool
    source: ToolCatalogSource
    exposure: ToolExposure


@dataclasses.dataclass(frozen=True)
class ToolSearchMatch:
    """One ranked deferred tool search result."""

    name: str
    description: str
    source_label: str
    score: float


@dataclasses.dataclass(frozen=True)
class ToolCatalogProjection:
    """Model-visible membership selected from one immutable executable catalog."""

    direct_tool_names: tuple[str, ...]
    active_deferred_tool_names: tuple[str, ...]
    visible_deferred_tool_names: tuple[str, ...]
    provider_visible_tool_names: tuple[str, ...]
    deferred_capacity: int | None


@dataclasses.dataclass(frozen=True)
class _IndexedTool:
    """Pre-tokenized BM25 document for one deferred tool."""

    entry: CatalogTool
    term_frequency: Counter[str]
    length: int


class DeferredToolSearchIndex:
    """Deterministic in-memory BM25 index over deferred executable tools."""

    def __init__(self, entries: Sequence[CatalogTool]) -> None:
        deferred = sorted(
            (entry for entry in entries if entry.exposure == ToolExposure.DEFERRED),
            key=lambda entry: entry.tool.spec.name,
        )
        self.entries = tuple(deferred)
        self.catalog_hash = _deferred_catalog_hash(self.entries)
        self._documents = tuple(_index_entry(entry) for entry in self.entries)
        self._document_frequency = _document_frequency(self._documents)
        self._average_document_length = (
            sum(document.length for document in self._documents) / len(self._documents)
            if self._documents
            else 0.0
        )

    def search(self, query: str, *, limit: int) -> list[ToolSearchMatch]:
        """Return positive-score matches ordered by relevance then final name."""
        if limit < 1 or limit > TOOL_SEARCH_MAX_RESULT_LIMIT:
            raise ValueError(
                "Tool Search limit must be between 1 and "
                f"{TOOL_SEARCH_MAX_RESULT_LIMIT}"
            )
        query_terms = _tokenize(query)
        if not query_terms or not self._documents:
            return []
        scored: list[ToolSearchMatch] = []
        for document in self._documents:
            score = self._score(document, query_terms)
            if score <= 0:
                continue
            scored.append(
                ToolSearchMatch(
                    name=document.entry.tool.spec.name,
                    description=document.entry.tool.spec.description,
                    source_label=document.entry.source.label,
                    score=score,
                )
            )
        scored.sort(key=lambda match: (-match.score, match.name))
        return scored[:limit]

    def _score(self, document: _IndexedTool, query_terms: Sequence[str]) -> float:
        """Calculate standard BM25 score for one indexed tool."""
        score = 0.0
        document_count = len(self._documents)
        for term in query_terms:
            frequency = document.term_frequency.get(term, 0)
            if frequency == 0:
                continue
            containing_documents = self._document_frequency[term]
            inverse_document_frequency = math.log(
                1
                + (document_count - containing_documents + 0.5)
                / (containing_documents + 0.5)
            )
            length_ratio = (
                document.length / self._average_document_length
                if self._average_document_length
                else 0.0
            )
            denominator = frequency + _BM25_K1 * (1 - _BM25_B + _BM25_B * length_ratio)
            score += inverse_document_frequency * (
                frequency * (_BM25_K1 + 1) / denominator
            )
        return score


class ToolWorkingSetState(ToolkitStateModel):
    """Session-scoped deferred-tool recency state, most recent first."""

    schema_version: int = TOOL_SEARCH_STATE_SCHEMA_VERSION
    tool_names: list[str] = Field(default_factory=list)

    @field_validator("tool_names")
    @classmethod
    def validate_tool_names(cls, value: list[str]) -> list[str]:
        """Reject blanks and normalize duplicate names to first occurrence."""
        normalized: list[str] = []
        seen: set[str] = set()
        for name in value:
            if not name.strip():
                raise ValueError("Tool working-set names cannot be blank")
            if name not in seen:
                normalized.append(name)
                seen.add(name)
        return normalized


class ToolWorkingSetStore:
    """Persist session Tool Search recency through Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        repository: ToolkitStateRepository | None = None,
    ) -> None:
        """Create one session-bound working-set store."""
        self.session_manager = session_manager
        self.repository = repository

    async def load(self, agent_id: str, session_id: str) -> ToolWorkingSetState:
        """Load the current session working set."""
        async with self.session_manager() as session:
            handle = self._handle(session, agent_id, session_id)
            return await handle.load(default_factory=ToolWorkingSetState)

    async def activate(
        self,
        agent_id: str,
        session_id: str,
        tool_names: Sequence[str],
    ) -> ToolWorkingSetState:
        """Move ranked search results to the recency front in supplied order."""
        activated = _unique_tool_names(tool_names)
        return await self._update(
            agent_id,
            session_id,
            lambda current: ToolWorkingSetState(
                tool_names=[
                    *activated,
                    *(name for name in current.tool_names if name not in activated),
                ]
            ),
        )

    async def touch(
        self,
        agent_id: str,
        session_id: str,
        tool_name: str,
    ) -> ToolWorkingSetState:
        """Move an invoked deferred tool to the most-recent position."""
        return await self.activate(agent_id, session_id, [tool_name])

    async def clear_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolWorkingSetState:
        """Clear working-set recency within a caller-owned transaction."""
        return await self._update_in_session(
            session,
            agent_id,
            session_id,
            lambda _: ToolWorkingSetState(),
        )

    async def _update(
        self,
        agent_id: str,
        session_id: str,
        mutator: Callable[[ToolWorkingSetState], ToolWorkingSetState],
    ) -> ToolWorkingSetState:
        """Update recency state using the shared optimistic-lock retry."""
        async with self.session_manager() as session:
            return await self._update_in_session(
                session,
                agent_id,
                session_id,
                mutator,
            )

    async def _update_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
        mutator: Callable[[ToolWorkingSetState], ToolWorkingSetState],
    ) -> ToolWorkingSetState:
        """Update recency state inside a caller-owned transaction."""
        handle = self._handle(session, agent_id, session_id)
        updated: ToolWorkingSetState | None = None

        def capture(current: ToolWorkingSetState) -> ToolWorkingSetState:
            nonlocal updated
            updated = mutator(current)
            return updated

        await handle.update(
            default_factory=ToolWorkingSetState,
            mutator=capture,
        )
        if updated is None:
            raise RuntimeError("Tool working-set update did not run")
        return updated

    def _handle(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[ToolWorkingSetState]:
        """Create the typed Toolkit State handle for one AgentSession."""
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=TOOL_SEARCH_TOOLKIT_NAMESPACE,
            state_name=TOOL_SEARCH_WORKING_SET_STATE_NAME,
        )
        return ToolkitStateStore(
            session=session,
            repository=self.repository,
        ).handle(identity, ToolWorkingSetState)


class ToolSearchInput(BaseModel):
    """Tool Search input schema."""

    query: str = Field(
        min_length=1,
        max_length=500,
        description="Concise description of the capability to find",
    )
    limit: int = Field(
        default=TOOL_SEARCH_DEFAULT_RESULT_LIMIT,
        ge=1,
        le=TOOL_SEARCH_MAX_RESULT_LIMIT,
        description="Maximum tools to activate",
    )


def project_tool_catalog(
    *,
    entries: Mapping[str, CatalogTool],
    working_set: ToolWorkingSetState,
    budget: ResolvedToolDeclarationBudget,
) -> ToolCatalogProjection:
    """Project shared session recency under one provider request budget."""
    direct_tool_names = tuple(
        sorted(
            name
            for name, entry in entries.items()
            if entry.exposure == ToolExposure.DIRECT
        )
    )
    ensure_pinned_direct_tools_fit(
        budget=budget,
        pinned_direct_function_declarations=len(direct_tool_names),
    )
    active_deferred_tool_names = tuple(
        name
        for name in working_set.tool_names
        if name in entries and entries[name].exposure == ToolExposure.DEFERRED
    )
    if budget.client_function_capacity is None:
        deferred_capacity = None
        visible_deferred_tool_names = active_deferred_tool_names
    else:
        deferred_capacity = max(
            0,
            budget.client_function_capacity - len(direct_tool_names),
        )
        visible_deferred_tool_names = active_deferred_tool_names[:deferred_capacity]
    provider_visible_tool_names = tuple(
        sorted((*direct_tool_names, *visible_deferred_tool_names))
    )
    return ToolCatalogProjection(
        direct_tool_names=direct_tool_names,
        active_deferred_tool_names=active_deferred_tool_names,
        visible_deferred_tool_names=visible_deferred_tool_names,
        provider_visible_tool_names=provider_visible_tool_names,
        deferred_capacity=deferred_capacity,
    )


def make_tool_search_tool(
    *,
    index: DeferredToolSearchIndex,
    store: ToolWorkingSetStore,
    agent_id: str,
    session_id: str,
    activation_capacity: int | None,
) -> FunctionTool:
    """Create the stable Tool Search function for one prepared catalog."""
    if activation_capacity is not None and activation_capacity < 0:
        raise ValueError("Tool Search activation capacity cannot be negative")

    async def tool_search(input: ToolSearchInput) -> str:
        """Search and activate deferred tools for the next prepared call."""
        effective_limit = (
            input.limit
            if activation_capacity is None
            else min(input.limit, activation_capacity)
        )
        matches = (
            index.search(input.query, limit=effective_limit)
            if effective_limit > 0
            else []
        )
        if matches:
            await store.activate(
                agent_id,
                session_id,
                [match.name for match in matches],
            )
        return json.dumps(
            {
                "activated_tools": [
                    {
                        "name": match.name,
                        "description": match.description,
                        "source": match.source_label,
                    }
                    for match in matches
                ],
                "requested_limit": input.limit,
                "activation_limit": activation_capacity,
                "limit_reduced": effective_limit < input.limit,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    return make_tool(
        tool_search,
        name="tool_search",
        description=_TOOL_SEARCH_DESCRIPTION,
    )


def classify_tool_exposure(
    *,
    source: ToolCatalogSource,
    original_tool_name: str,
) -> ToolExposure:
    """Classify core tools as direct and attached service operations as deferred."""
    if source.toolkit_type is None:
        return ToolExposure.DIRECT
    if (source.toolkit_type, original_tool_name) in _DIRECT_REGISTERED_TOOLS:
        return ToolExposure.DIRECT
    return ToolExposure.DEFERRED


def _index_entry(entry: CatalogTool) -> _IndexedTool:
    tokens = _search_document_tokens(entry)
    return _IndexedTool(
        entry=entry,
        term_frequency=Counter(tokens),
        length=len(tokens),
    )


def _search_document_tokens(entry: CatalogTool) -> list[str]:
    tool = entry.tool
    source = entry.source
    values = [
        tool.spec.name,
        tool.spec.description,
        source.slug,
        source.toolkit_type or "",
        source.toolkit_class,
        source.display_name,
        *(value for pair in source.routing_metadata for value in pair),
        *_schema_search_values(tool.spec.input_schema),
    ]
    return [token for value in values for token in _tokenize(value)]


def _schema_search_values(value: object) -> list[str]:
    """Collect parameter names and descriptions from a JSON Schema tree."""
    if isinstance(value, Mapping):
        result: list[str] = []
        properties = value.get("properties")
        if isinstance(properties, Mapping):
            for name, property_schema in properties.items():
                result.append(str(name))
                result.extend(_schema_search_values(property_schema))
        for key in ("description", "title"):
            text = value.get(key)
            if isinstance(text, str):
                result.append(text)
        for key, nested in value.items():
            if key not in {"properties", "description", "title"}:
                result.extend(_schema_search_values(nested))
        return result
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [text for item in value for text in _schema_search_values(item)]
    return []


def _document_frequency(documents: Sequence[_IndexedTool]) -> Counter[str]:
    frequency: Counter[str] = Counter()
    for document in documents:
        frequency.update(document.term_frequency.keys())
    return frequency


def _deferred_catalog_hash(entries: Sequence[CatalogTool]) -> str:
    payload = [
        {
            "name": entry.tool.spec.name,
            "description": entry.tool.spec.description,
            "input_schema": entry.tool.spec.input_schema,
            "source": dataclasses.asdict(entry.source),
        }
        for entry in entries
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _tokenize(value: str) -> list[str]:
    return _TOKEN_PATTERN.findall(value.lower())


def _unique_tool_names(tool_names: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        if not name.strip():
            raise ValueError("Tool working-set names cannot be blank")
        if name not in seen:
            unique.append(name)
            seen.add(name)
    return unique
