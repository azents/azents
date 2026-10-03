"""Tests for the live read-only Memory VFS backend."""

import asyncio
import dataclasses
import datetime
import json
import re
from collections.abc import Sequence
from typing import Literal

import pytest

import azents.services.memory_vfs as memory_vfs_module
from azents.core.enums import (
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.core.vfs import (
    VFS_FILE_MAX_BYTES,
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    NativeArtifact,
    build_native_compat_key,
)
from azents.repos.memory_vfs.data import (
    ConsolidatedMemoryVfsRecord,
    HistoricalMemoryVfsRecord,
    MemoryVfsAuthority,
    MemoryVfsRecordPage,
    MemoryVfsUriPage,
    MemoryVfsUriQuery,
    SavedMemoryVfsRecord,
    SourceEventVfsRecord,
    SourceSessionVfsRecord,
    ToolResultVfsRecord,
)
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.services.memory_vfs import MemoryVfsReadBackend
from azents.services.vfs_read import VfsReadContext, VfsReadError

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_SESSION_ID = "s" * 32
_EVENT_ID = "e" * 32
_MEMORY_ID = "m" * 32


class _Repository(MemoryVfsRepository):
    """Small typed repository double for backend routing and rendering."""

    def __init__(self) -> None:
        self.authorized_result = True
        self.saved_available = True
        self.saved = SavedMemoryVfsRecord(
            memory_id=_MEMORY_ID,
            scope="agent",
            memory_type="project",
            name="Release plan",
            description="Current release direction",
            content="Ship the Memory VFS after verification.",
            created_at=_NOW,
            updated_at=_NOW,
        )
        self.historical = HistoricalMemoryVfsRecord(
            source_session_id=_SESSION_ID,
            scope="team",
            source_title="Earlier work",
            source_activity_through=_NOW,
            prepared_at=_NOW,
            summary="The team approved the bounded VFS direction.",
        )
        self.source = SourceSessionVfsRecord(
            session_id=_SESSION_ID,
            scope="team",
            title="Earlier work",
            handle="earlier-work",
            last_activity_at=_NOW,
            latest_visible_event_id=_EVENT_ID,
            summary_available=True,
        )
        self.event = SourceEventVfsRecord(
            scope="team",
            event=_external_event(),
            previous_event_id=None,
            next_event_id=None,
            paired_client_result=None,
        )
        self.tool_result = ToolResultVfsRecord(
            scope="team",
            session_id=_SESSION_ID,
            event_id=_EVENT_ID,
            tool_name="exec_command",
            status="completed",
            text="bounded result text",
            created_at=_NOW,
        )
        self.listed_saved: tuple[SavedMemoryVfsRecord, ...] = (self.saved,)
        self.listed_historical: tuple[HistoricalMemoryVfsRecord, ...] = (
            self.historical,
        )
        self.listed_sources: tuple[SourceSessionVfsRecord, ...] = (self.source,)
        self.listed_events: tuple[SourceEventVfsRecord, ...] = (self.event,)
        self.list_saved_calls = 0
        self.list_historical_calls = 0
        self.list_sources_calls = 0
        self.list_events_calls = 0
        self.uri_page = MemoryVfsUriPage(
            (
                "azents://memory/README.md",
                f"azents://memory/saved/agent/{_MEMORY_ID}.md",
                f"azents://memory/sources/team/{_SESSION_ID}/session.md",
            ),
            False,
        )
        self.uri_queries: list[MemoryVfsUriQuery] = []
        self.uri_pages_by_namespace: dict[str, MemoryVfsUriPage] = {}

    async def authorized(self, authority: MemoryVfsAuthority) -> bool:
        del authority
        return self.authorized_result

    async def get_consolidated(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        max_bytes: int,
    ) -> ConsolidatedMemoryVfsRecord | None:
        del authority, scope, max_bytes
        return None

    async def get_saved(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["agent", "user"],
        memory_id: str,
        max_bytes: int,
    ) -> SavedMemoryVfsRecord | None:
        del authority, scope, memory_id, max_bytes
        return self.saved if self.saved_available else None

    async def list_saved(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["agent", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        del authority, scopes, limit, max_bytes
        self.list_saved_calls += 1
        return MemoryVfsRecordPage(self.listed_saved, False)

    async def get_historical(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        source_session_id: str,
        max_bytes: int,
    ) -> HistoricalMemoryVfsRecord | None:
        del authority, scope, source_session_id, max_bytes
        return self.historical

    async def list_historical(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        del authority, scopes, limit, max_bytes
        self.list_historical_calls += 1
        return MemoryVfsRecordPage(self.listed_historical, False)

    async def get_source(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        max_bytes: int,
    ) -> SourceSessionVfsRecord | None:
        del authority, scope, session_id, max_bytes
        return self.source

    async def list_sources(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        del authority, scopes, limit, max_bytes
        self.list_sources_calls += 1
        return MemoryVfsRecordPage(self.listed_sources, False)

    async def get_event(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        event_id: str,
        max_bytes: int,
    ) -> SourceEventVfsRecord | None:
        del authority, scope, session_id, event_id, max_bytes
        return self.event

    async def list_events(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        limit: int,
    ) -> MemoryVfsRecordPage:
        del authority, scope, session_id, limit
        self.list_events_calls += 1
        return MemoryVfsRecordPage(self.listed_events, False)

    async def list_event_candidates(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        session_id: str | None,
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        del authority, scopes, session_id, limit, max_bytes
        self.list_events_calls += 1
        return MemoryVfsRecordPage(self.listed_events, False)

    async def get_tool_result(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        event_id: str,
        max_bytes: int,
    ) -> ToolResultVfsRecord | None:
        del authority, scope, session_id, event_id, max_bytes
        return self.tool_result

    async def list_tool_results(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        limit: int,
    ) -> MemoryVfsRecordPage:
        del authority, scope, session_id, limit
        return MemoryVfsRecordPage((self.tool_result,), False)

    async def list_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        query: MemoryVfsUriQuery,
        limit: int,
    ) -> MemoryVfsUriPage:
        del authority, limit
        self.uri_queries.append(query)
        return self.uri_pages_by_namespace.get(query.namespace, self.uri_page)


class _StalledRepository(_Repository):
    """Repository double that never completes current authorization."""

    async def authorized(self, authority: MemoryVfsAuthority) -> bool:
        del authority
        await asyncio.Event().wait()
        return True


def _context(*, memory_enabled: bool = True) -> VfsReadContext:
    return VfsReadContext(
        run_id="r" * 32,
        session_id="c" * 32,
        root_session_id="c" * 32,
        agent_id="a" * 32,
        workspace_id="w" * 32,
        associated_user_id=None,
        owner_generation=1,
        memory_enabled=memory_enabled,
    )


def _external_event() -> Event:
    payload = ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.DISCORD,
        provider_tenant_id="tenant",
        resource_id="channel",
        resource_label="#memory",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding",
        invocation_batch_id="batch",
        external_message_id="message",
        projection_root_id="external-channel:binding:message",
        provider_message_key="discord:message",
        provider_position="1",
        principal_id=None,
        provider_user_id="user",
        sender_display_name="Reviewer",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        prompt_role="invocation",
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        body="Use token=secret only for this request.",
        attachment_metadata={},
        reference_mappings={},
        provider_created_at=_NOW,
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
    )
    return Event(
        id=_EVENT_ID,
        session_id=_SESSION_ID,
        kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
        payload=payload,
        external_id=None,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        schema_version="1",
        created_at=_NOW,
    )


def _channel_action_event_pair() -> tuple[Event, Event]:
    compat_key = build_native_compat_key(
        adapter="pydantic_ai",
        native_format="model_messages",
        provider="openai",
        model="gpt-test",
        schema_version="1",
    )
    artifact = NativeArtifact(
        compat_key=compat_key,
        adapter="pydantic_ai",
        native_format="model_messages",
        provider="openai",
        model="gpt-test",
        schema_version="1",
        item={"type": "function_call"},
    )
    call = Event(
        id=_EVENT_ID,
        session_id=_SESSION_ID,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="channel_action",
            arguments=json.dumps(
                {
                    "mode": "continue",
                    "binding": "binding-1",
                    "message": "Published update",
                    "todo_update": [
                        {
                            "id": "done",
                            "title": "Publish",
                            "status": "completed",
                            "output": {"token": "secret"},
                        }
                    ],
                }
            ),
            wire_dialect="json_function",
            native_artifact=artifact,
        ),
        external_id=None,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        schema_version="1",
        created_at=_NOW,
    )
    result = Event(
        id="r" * 32,
        session_id=_SESSION_ID,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            name="channel_action",
            wire_dialect="json_function",
            status="completed",
            output=json.dumps(
                {
                    "outcomes": [
                        {
                            "operation": "reply",
                            "part": 0,
                            "status": "delivered",
                        }
                    ]
                }
            ),
        ),
        external_id=None,
        adapter=None,
        provider=None,
        model=None,
        native_format=None,
        schema_version="1",
        created_at=_NOW,
    )
    return call, result


def _backend(repository: MemoryVfsRepository | None = None) -> MemoryVfsReadBackend:
    return MemoryVfsReadBackend(repository=repository or _Repository())


async def test_read_saved_memory_renders_safe_metadata_and_pages_text() -> None:
    """Exact Saved reads include full content and preserve character paging."""
    backend = _backend()
    location = parse_vfs_exact_uri(f"azents://memory/saved/agent/{_MEMORY_ID}.md")

    complete = await backend.read_text(
        _context(),
        location,
        offset=0,
        limit=10_000,
        encoding="utf-8",
    )
    partial = await backend.read_text(
        _context(),
        location,
        offset=0,
        limit=12,
        encoding="utf-8",
    )

    assert "kind: saved_memory" in complete.text
    assert "Ship the Memory VFS after verification." in complete.text
    assert partial.truncated is True
    assert partial.text == complete.text[:12]


async def test_read_source_event_redacts_sensitive_assignments() -> None:
    """External metadata and body redact assignments and URL query values."""
    repository = _Repository()
    payload = repository.event.event.payload
    assert isinstance(payload, ExternalChannelMessagePayload)
    repository.event = dataclasses.replace(
        repository.event,
        event=repository.event.event.model_copy(
            update={
                "payload": payload.model_copy(
                    update={
                        "resource_label": (
                            "https://example.test/channel?token=resource-secret"
                        ),
                        "sender_display_name": "password=sender-secret",
                        "body": (
                            "Use token=body-secret and "
                            "https://example.test/item?api_key=url-secret"
                        ),
                    }
                )
            }
        ),
    )

    result = await _backend(repository).read_text(
        _context(),
        parse_vfs_exact_uri(
            f"azents://memory/sources/team/{_SESSION_ID}/events/{_EVENT_ID}.md"
        ),
        offset=0,
        limit=10_000,
        encoding="utf-8",
    )

    assert "External Channel message" in result.text
    assert "resource-secret" not in result.text
    assert "sender-secret" not in result.text
    assert "body-secret" not in result.text
    assert "url-secret" not in result.text
    assert result.text.count("[REDACTED]") >= 3


async def test_exact_read_timeout_and_backend_file_bound_are_non_enumerating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stalled and oversized exact reads fail within the common safe boundary."""
    monkeypatch.setattr(memory_vfs_module, "_MEMORY_OPERATION_MAX_SECONDS", 0.01)
    with pytest.raises(VfsReadError, match="unavailable"):
        await _backend(_StalledRepository()).read_text(
            _context(),
            parse_vfs_exact_uri("azents://memory/README.md"),
            offset=0,
            limit=100,
            encoding="utf-8",
        )

    repository = _Repository()
    repository.saved = dataclasses.replace(
        repository.saved,
        content="x" * (VFS_FILE_MAX_BYTES + 1),
    )
    with pytest.raises(VfsReadError, match="unavailable"):
        await _backend(repository).read_text(
            _context(),
            parse_vfs_exact_uri(f"azents://memory/saved/agent/{_MEMORY_ID}.md"),
            offset=0,
            limit=100,
            encoding="utf-8",
        )


async def test_read_registered_conversational_tool_event_preserves_delivery() -> None:
    """Registered tool-mediated conversation retains delivery and redaction."""
    repository = _Repository()
    call, result = _channel_action_event_pair()
    repository.event = SourceEventVfsRecord(
        scope="team",
        event=call,
        previous_event_id=None,
        next_event_id=None,
        paired_client_result=result,
    )

    rendered = await _backend(repository).read_text(
        _context(),
        parse_vfs_exact_uri(
            f"azents://memory/sources/team/{_SESSION_ID}/events/{_EVENT_ID}.md"
        ),
        offset=0,
        limit=10_000,
        encoding="utf-8",
    )

    assert "Published update" in rendered.text
    assert "delivery=delivered" in rendered.text
    assert "secret" not in rendered.text
    assert "[REDACTED]" in rendered.text


async def test_exact_tool_result_is_readable_but_broad_grep_is_unsupported() -> None:
    """Tool-result bodies require exact authorized reads."""
    backend = _backend()
    path = f"azents://memory/sources/team/{_SESSION_ID}/tool-results/{_EVENT_ID}.txt"

    result = await backend.read_text(
        _context(),
        parse_vfs_exact_uri(path),
        offset=0,
        limit=10_000,
        encoding="utf-8",
    )

    assert "bounded result text" in result.text
    with pytest.raises(VfsReadError, match="exact read"):
        await backend.grep(
            _context(),
            parse_vfs_search_uri(
                f"azents://memory/sources/team/{_SESSION_ID}/tool-results"
            ),
            pattern=re.compile("bounded"),
            recursive=True,
            exclude_patterns=(),
            max_matching_files=10,
            max_lines_per_file=10,
            max_searched_files=10,
            max_scanned_bytes=10_000,
        )


async def test_grep_searches_saved_historical_and_semantic_events() -> None:
    """Broad grep returns canonical matches without tool-result bodies."""
    backend = _backend()

    result = await backend.grep(
        _context(),
        parse_vfs_search_uri("azents://memory"),
        pattern=re.compile("Ship|approved|Reviewer"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=10,
        max_searched_files=20,
        max_scanned_bytes=100_000,
    )

    paths = {item.path for item in result.files}
    assert f"azents://memory/saved/agent/{_MEMORY_ID}.md" in paths
    assert f"azents://memory/historical/team/{_SESSION_ID}/summary.md" in paths
    assert f"azents://memory/sources/team/{_SESSION_ID}/events/{_EVENT_ID}.md" in paths
    assert all("tool-results" not in path for path in paths)


async def test_grep_tiny_scan_budget_truncates_without_unbounded_queries() -> None:
    """A byte budget smaller than the query count skips later body queries."""
    result = await _backend().grep(
        _context(),
        parse_vfs_search_uri("azents://memory"),
        pattern=re.compile("anything"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=10,
        max_searched_files=20,
        max_scanned_bytes=1,
    )

    assert result.files == ()
    assert result.truncated is True
    assert result.stopped_reason == "scanned_byte_limit"


async def test_exact_saved_grep_is_not_starved_by_bounded_listing() -> None:
    """An exact file lookup bypasses earlier-sorted directory results."""
    repository = _Repository()
    target_id = "z" * 32
    repository.saved = dataclasses.replace(
        repository.saved,
        memory_id=target_id,
        content="exact target needle",
    )
    repository.listed_saved = (
        dataclasses.replace(
            repository.saved,
            memory_id="a" * 32,
            content="unrelated",
        ),
    )

    result = await _backend(repository).grep(
        _context(),
        parse_vfs_search_uri(f"azents://memory/saved/agent/{target_id}.md"),
        pattern=re.compile("exact target"),
        recursive=False,
        exclude_patterns=(),
        max_matching_files=1,
        max_lines_per_file=10,
        max_searched_files=1,
        max_scanned_bytes=10_000,
    )

    assert [item.path for item in result.files] == [
        f"azents://memory/saved/agent/{target_id}.md"
    ]
    assert repository.list_saved_calls == 0


async def test_exact_historical_and_event_grep_bypass_global_pages() -> None:
    """Exact source IDs and event IDs use authorized point queries first."""
    repository = _Repository()
    target_session_id = "z" * 32
    target_event_id = "y" * 32
    repository.historical = dataclasses.replace(
        repository.historical,
        source_session_id=target_session_id,
        summary="exact historical needle",
    )
    repository.source = dataclasses.replace(
        repository.source,
        session_id=target_session_id,
        latest_visible_event_id=target_event_id,
    )
    repository.event = dataclasses.replace(
        repository.event,
        event=repository.event.event.model_copy(
            update={
                "id": target_event_id,
                "session_id": target_session_id,
                "payload": repository.event.event.payload.model_copy(
                    update={"body": "exact event needle"}
                ),
            }
        ),
    )
    repository.listed_historical = (
        dataclasses.replace(
            repository.historical,
            source_session_id="a" * 32,
            summary="unrelated",
        ),
    )
    repository.listed_sources = (
        dataclasses.replace(repository.source, session_id="a" * 32),
    )
    repository.listed_events = (
        dataclasses.replace(
            repository.event,
            event=repository.event.event.model_copy(update={"id": "a" * 32}),
        ),
    )

    historical = await _backend(repository).grep(
        _context(),
        parse_vfs_search_uri(f"azents://memory/historical/team/{target_session_id}"),
        pattern=re.compile("exact historical"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=1,
        max_lines_per_file=10,
        max_searched_files=1,
        max_scanned_bytes=10_000,
    )
    event = await _backend(repository).grep(
        _context(),
        parse_vfs_search_uri(
            "azents://memory/sources/team/"
            f"{target_session_id}/events/{target_event_id}.md"
        ),
        pattern=re.compile("exact event"),
        recursive=False,
        exclude_patterns=(),
        max_matching_files=1,
        max_lines_per_file=10,
        max_searched_files=1,
        max_scanned_bytes=10_000,
    )

    assert [item.path for item in historical.files] == [
        f"azents://memory/historical/team/{target_session_id}/summary.md"
    ]
    assert [item.path for item in event.files] == [
        f"azents://memory/sources/team/{target_session_id}/events/{target_event_id}.md"
    ]
    assert repository.list_historical_calls == 0
    assert repository.list_sources_calls == 0
    assert repository.list_events_calls == 0


async def test_glob_returns_only_matching_sorted_authorized_uris() -> None:
    """Glob filters the bounded repository inventory deterministically."""
    backend = _backend()

    result = await backend.glob(
        _context(),
        parse_vfs_glob_pattern("azents://memory/**/*.md"),
        exclude_patterns=("README.md",),
    )

    assert result.uris == (
        f"azents://memory/saved/agent/{_MEMORY_ID}.md",
        f"azents://memory/sources/team/{_SESSION_ID}/session.md",
    )
    assert result.truncated is False


async def test_glob_queries_only_literal_namespace_scope_and_session_prefix() -> None:
    """Narrow glob roots are not starved by unrelated global inventory."""
    repository = _Repository()
    target_session_id = "z" * 32
    target_event_id = "y" * 32
    unrelated = tuple(
        f"azents://memory/historical/team/{index:032x}/summary.md"
        for index in range(1_000)
    )
    repository.uri_page = MemoryVfsUriPage(unrelated, True)
    repository.uri_pages_by_namespace["sources"] = MemoryVfsUriPage(
        (
            "azents://memory/sources/team/"
            f"{target_session_id}/events/{target_event_id}.md",
        ),
        False,
    )

    result = await _backend(repository).glob(
        _context(),
        parse_vfs_glob_pattern(
            f"azents://memory/sources/team/{target_session_id}/events/*.md"
        ),
        exclude_patterns=(),
    )

    assert result.uris == (
        f"azents://memory/sources/team/{target_session_id}/events/{target_event_id}.md",
    )
    assert result.truncated is False
    assert repository.uri_queries == [
        MemoryVfsUriQuery(
            namespace="sources",
            saved_scopes=("agent", "user"),
            source_scopes=("team",),
            session_id=target_session_id,
            source_file_kinds=("events",),
            include_readme=False,
        )
    ]


async def test_memory_disabled_and_denied_paths_are_non_enumerating() -> None:
    """Disablement and denied exact paths share one unavailable result."""
    repository = _Repository()
    backend = _backend(repository)
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.read_text(
            _context(memory_enabled=False),
            parse_vfs_exact_uri("azents://memory/README.md"),
            offset=0,
            limit=100,
            encoding="utf-8",
        )

    repository.authorized_result = False
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.read_text(
            _context(),
            parse_vfs_exact_uri("azents://memory/README.md"),
            offset=0,
            limit=100,
            encoding="utf-8",
        )
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.glob(
            _context(),
            parse_vfs_glob_pattern("azents://memory/**"),
            exclude_patterns=(),
        )

    repository.authorized_result = True
    repository.saved_available = False
    with pytest.raises(VfsReadError, match="unavailable"):
        await backend.grep(
            _context(),
            parse_vfs_search_uri(f"azents://memory/saved/agent/{_MEMORY_ID}.md"),
            pattern=re.compile("missing"),
            recursive=True,
            exclude_patterns=(),
            max_matching_files=10,
            max_lines_per_file=10,
            max_searched_files=10,
            max_scanned_bytes=10_000,
        )
