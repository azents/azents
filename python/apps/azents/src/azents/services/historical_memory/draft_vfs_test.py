"""Real PostgreSQL Runtime-free draft routing and admission regressions."""

import asyncio
import dataclasses
import json
import re
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.historical_memory_consolidation import ConsolidationJobPrincipal
from azents.core.vfs import (
    parse_vfs_exact_uri,
    parse_vfs_search_uri,
)
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolSpec,
)
from azents.engine.tooling.execution_context import (
    client_tool_execution_context,
)
from azents.engine.tools.read_text import make_read_text_tool
from azents.engine.tools.readable_storage import RoutedReadableStorage
from azents.rdb.session import SessionManager
from azents.repos.historical_memory_consolidation.drafts import (
    ConsolidationDraftRepository,
    DraftFileChange,
    DraftFileObservation,
)
from azents.services.historical_memory.draft_vfs import ConsolidationDraftVfsBackend
from azents.services.vfs_mutation import (
    VfsAtomicPatchRequest,
    VfsBackendRegistration,
    VfsEditRequest,
    VfsMutationCapabilities,
    VfsMutationError,
)
from azents.services.vfs_read import (
    VfsReadError,
)
from azents.testing.consolidation_vfs import (
    bind_consolidation_test_vfs as _binding,
)
from azents.testing.consolidation_vfs import (
    invoke_consolidation_test_tool as _invoke,
)
from azents.testing.consolidation_vfs import (
    read_consolidation_test_uri as _read,
)

_URI = "azents://memory-draft/summary.md"


async def test_generic_create_read_edit_delete_and_replay_without_runtime(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    assert set(tools) == {"write", "edit", "delete", "apply_patch"}
    with client_tool_execution_context(call_id="create", name="qualified__write"):
        await tools["write"].handler(
            json.dumps({"path": _URI, "content": "first 한글"})
        )
    with pytest.raises(FunctionToolError, match="before overwrite"):
        await _invoke(
            tools["write"],
            "unread",
            {"path": _URI, "content": "unsafe", "overwrite": True},
        )
    assert (await _read(binding, _URI)).text == "first 한글"
    edit = {"path": _URI, "old_string": "first", "new_string": "second"}
    original = await _invoke(tools["edit"], "edit", edit)
    # Replay is checked before applicability against the now-changed text.
    assert await _invoke(tools["edit"], "edit", edit) == original
    assert (await _read(binding, _URI)).text == "second 한글"
    deleted = await _invoke(tools["delete"], "delete", {"path": _URI})
    with pytest.raises(VfsReadError, match="absent"):
        await _read(binding, _URI)
    assert await _invoke(tools["delete"], "delete", {"path": _URI}) == deleted
    with pytest.raises(FunctionToolError, match="Runtime file mutation is unavailable"):
        await _invoke(
            tools["write"], "absolute", {"path": "/tmp/denied", "content": "no"}
        )
    for tool in tools.values():
        schema = json.dumps(tool.spec.input_schema)
        assert "owner_generation" not in schema and "evidence_epoch" not in schema
        assert "revision_id" not in schema and "attempt_id" not in schema


async def test_readonly_and_unknown_vfs_never_fall_back_to_runtime(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    runtime = AsyncMock(return_value="native runtime result")
    native = FunctionTool(
        FunctionToolSpec(name="write", description="native", input_schema={}), runtime
    )
    tools = binding.tools({"write": native})
    for uri in (
        "azents://memory/anything.md",
        "azents://skills/global/SKILL.md",
        "azents://memory-draft/../escaped.md",
    ):
        with pytest.raises(FunctionToolError):
            await _invoke(tools["write"], "denied", {"path": uri, "content": "no"})
    runtime.assert_not_awaited()
    assert (
        await _invoke(
            tools["write"], "native", {"path": "/tmp/native", "content": "yes"}
        )
        == "native runtime result"
    )
    runtime.assert_awaited_once()


async def test_queued_write_keeps_old_evidence_after_another_read(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "before"})
    await _read(binding, _URI)
    admitted = binding.mutations.admit(
        binding.principal,
        VfsEditRequest(parse_vfs_exact_uri(_URI), "before", "after", False),
        tool_call_id="queued",
    )
    # A later source exposure and fresh file read cannot replace the frozen ticket.
    page = await binding.source.repository.inventory(
        binding.principal, after=None, limit=10, source_id_prefix=None
    )
    assert len(page.entries) == 1
    await _read(
        binding, binding.source.source_uri(page.entries[0].version.source_session_id)
    )
    await _read(binding, _URI)
    with pytest.raises(VfsMutationError, match="stale"):
        await binding.mutations.execute(admitted)
    assert (await _read(binding, _URI)).text == "before"


async def test_two_admitted_writes_do_not_silently_rebase_on_each_other(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "before"})
    await _read(binding, _URI)
    request = VfsEditRequest(parse_vfs_exact_uri(_URI), "before", "after", False)
    first = binding.mutations.admit(binding.principal, request, tool_call_id="first")
    second = binding.mutations.admit(binding.principal, request, tool_call_id="second")
    await binding.mutations.execute(first)
    await _read(binding, _URI)
    with pytest.raises(VfsMutationError, match="stale"):
        await binding.mutations.execute(second)


async def test_private_alias_is_not_authority_and_optional_patch_has_no_stub(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    wrong = binding.principal.model_copy(update={"owner_token": "x" * 32})
    with pytest.raises(VfsReadError):
        await binding.reads.read_text(
            wrong, _URI, offset=0, limit=100, encoding="utf-8"
        )
    with pytest.raises(VfsMutationError, match="does not support atomic patch"):
        binding.mutations.admit_patch(
            binding.principal,
            VfsAtomicPatchRequest(
                parse_vfs_search_uri("azents://memory"),
                "*** Begin Patch\n*** End Patch\n",
            ),
            tool_call_id="optional",
        )
    with pytest.raises(ValueError, match="capabilities"):
        VfsBackendRegistration(
            binding.source, None, None, VfsMutationCapabilities(True, False)
        )


async def test_unicode_bounds_inventory_and_native_search(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "한" * 9000})
    result = await _read(binding, _URI)
    assert len(result.text.encode("utf-8")) == 10998 and result.truncated
    rest = await binding.reads.read_text(
        binding.principal,
        _URI,
        offset=result.end_character,
        limit=10000,
        encoding="utf-8",
    )
    assert rest.start_character == 3666 and rest.text == "한" * 3666
    glob = await binding.reads.glob(
        binding.principal, "azents://memory-draft/**", exclude_patterns=()
    )
    assert glob.uris == (_URI,)
    inventory = await _read(binding, "azents://memory/inventory/README.md")
    assert "team/" in inventory.text and "/user/" not in inventory.text
    search = await binding.reads.grep(
        binding.principal,
        "azents://memory",
        pattern=re.compile("sentinel"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=50,
        max_lines_per_file=10,
        max_searched_files=50,
        max_scanned_bytes=12000,
    )
    assert search.matched_file_count == 1
    assert "team sentinel" in search.files[0].lines[0].text
    storage = RoutedReadableStorage(
        agent_id=binding.principal.unit.agent_id,
        vfs_router=binding.reads,
        vfs_context=binding.principal,
        runtime_storage_factory=None,
        runtime_capability_resolver=None,
    )
    read_tool = make_read_text_tool(
        session_storage=storage, agent_id=binding.principal.unit.agent_id
    )
    body = await read_tool.handler(json.dumps({"path": _URI, "limit": 10000}))
    assert isinstance(body, str) and len(body.encode("utf-8")) <= 12000
    with pytest.raises(FunctionToolError, match="unavailable"):
        await storage.get_text(
            "/tmp/no-runtime",
            agent_id=binding.principal.unit.agent_id,
            offset=0,
            limit=10,
            encoding="utf-8",
        )


async def test_mixed_revision_continuation_invalidates_all_mutation_admission(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "old prefix"})
    first = await binding.reads.read_text(
        binding.principal, _URI, offset=0, limit=4, encoding="utf-8"
    )
    old = binding.draft.observations.files[_URI]
    await binding.draft.repository.mutate(
        binding.principal,
        tool_call_id="external",
        request_digest="a" * 64,
        expected_draft_revision_id=old.draft_revision_id,
        expected_observation_epoch=old.observation_epoch,
        changes=[DraftFileChange("summary.md", old.file_revision_id, "new prefix")],
    )
    with pytest.raises(VfsReadError, match="offset 0"):
        await binding.reads.read_text(
            binding.principal,
            _URI,
            offset=first.end_character,
            limit=100,
            encoding="utf-8",
        )
    assert _URI not in binding.draft.observations.files
    for name, arguments in (
        ("write", {"path": _URI, "content": "unsafe", "overwrite": True}),
        ("edit", {"path": _URI, "old_string": "new", "new_string": "unsafe"}),
        ("delete", {"path": _URI}),
        (
            "apply_patch",
            {
                "base_path": "azents://memory-draft",
                "patch": (
                    "*** Begin Patch\n*** Delete File: summary.md\n*** End Patch\n"
                ),
            },
        ),
    ):
        with pytest.raises(FunctionToolError, match="Read|read"):
            await _invoke(tools[name], f"denied-{name}", arguments)
    with pytest.raises(VfsReadError, match="offset 0"):
        await binding.reads.read_text(
            binding.principal, _URI, offset=4, limit=100, encoding="utf-8"
        )
    assert (await _read(binding, _URI)).text == "new prefix"
    await _invoke(
        tools["edit"],
        "fresh",
        {"path": _URI, "old_string": "new", "new_string": "safe"},
    )
    assert (await _read(binding, _URI)).text == "safe prefix"


@dataclasses.dataclass(frozen=True)
class _DelayedDraftRepository(ConsolidationDraftRepository):
    observed: asyncio.Event
    release: asyncio.Event

    async def observe(
        self, principal: ConsolidationJobPrincipal, *, path: str
    ) -> DraftFileObservation:
        observation = await super().observe(principal, path=path)
        self.observed.set()
        await self.release.wait()  # The repository transaction is already closed.
        return observation


@pytest.mark.parametrize("restart", [False, True])
async def test_delayed_chunk_cannot_rehabilitate_conflict_or_replace_restart(
    rdb_session_manager: SessionManager[AsyncSession], restart: bool
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "old prefix"})
    await _read(binding, _URI)
    old = binding.draft.observations.files[_URI]
    observed, release = asyncio.Event(), asyncio.Event()
    delayed = ConsolidationDraftVfsBackend(
        _DelayedDraftRepository(rdb_session_manager, observed, release),
        binding.draft.observations,
    )
    task = asyncio.create_task(
        delayed.read_text(
            binding.principal,
            parse_vfs_exact_uri(_URI),
            offset=4,
            limit=100,
            encoding="utf-8",
        )
    )
    await observed.wait()
    try:
        await binding.draft.repository.mutate(
            binding.principal,
            tool_call_id="external",
            request_digest="a" * 64,
            expected_draft_revision_id=old.draft_revision_id,
            expected_observation_epoch=old.observation_epoch,
            changes=[DraftFileChange("summary.md", old.file_revision_id, "new prefix")],
        )
        with pytest.raises(VfsReadError, match="offset 0"):
            await binding.reads.read_text(
                binding.principal, _URI, offset=4, limit=100, encoding="utf-8"
            )
        if restart:
            assert (await _read(binding, _URI)).text == "new prefix"
        release.set()
        with pytest.raises(VfsReadError, match="offset 0"):
            await task
        if restart:
            assert binding.draft.observations.files[_URI].content == "new prefix"
        else:
            assert _URI not in binding.draft.observations.files
    finally:
        release.set()
        if not task.done():
            await task


async def test_initial_read_completing_after_newer_chunk_invalidates_mixed_evidence(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "old prefix"})
    await _read(binding, _URI)
    old = binding.draft.observations.files[_URI]
    observed, release = asyncio.Event(), asyncio.Event()
    delayed = ConsolidationDraftVfsBackend(
        _DelayedDraftRepository(rdb_session_manager, observed, release),
        binding.draft.observations,
    )
    task = asyncio.create_task(
        delayed.read_text(
            binding.principal,
            parse_vfs_exact_uri(_URI),
            offset=0,
            limit=4,
            encoding="utf-8",
        )
    )
    await observed.wait()
    try:
        await binding.draft.repository.mutate(
            binding.principal,
            tool_call_id="external",
            request_digest="a" * 64,
            expected_draft_revision_id=old.draft_revision_id,
            expected_observation_epoch=old.observation_epoch,
            changes=[DraftFileChange("summary.md", old.file_revision_id, "new prefix")],
        )
        # A later chunk completes first in this same read generation.
        assert (
            await binding.reads.read_text(
                binding.principal, _URI, offset=4, limit=100, encoding="utf-8"
            )
        ).text == "prefix"
        release.set()
        with pytest.raises(VfsReadError, match="offset 0"):
            await task
        assert _URI not in binding.draft.observations.files
        assert (await _read(binding, _URI)).text == "new prefix"
    finally:
        release.set()
        if not task.done():
            await task
