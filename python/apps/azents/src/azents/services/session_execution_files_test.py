"""Native current files: scope isolation, independent applicability and atomic patch."""

import dataclasses
import re

import pytest
import sqlalchemy as sa

from azents.core.vfs import (
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.engine.run.types import FunctionToolResult, PlaintextCustomToolHandler
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.services.vfs_mutation import (
    VfsAtomicPatchRequest,
    VfsDeleteRequest,
    VfsEditRequest,
    VfsMutationError,
    VfsWriteRequest,
)
from azents.services.vfs_read import VfsReadError
from azents.testing.consolidation_vfs import (
    bind_consolidation_test_vfs,
    invoke_consolidation_test_tool,
    read_consolidation_test_uri,
)

_URI = "azents://execution/summary.md"


async def test_create_observe_edit_delete_and_independent_paths(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    tools = binding.tools({})
    await invoke_consolidation_test_tool(
        tools["write"], "create", {"path": _URI, "content": "before"}
    )
    await read_consolidation_test_uri(binding, _URI)
    await invoke_consolidation_test_tool(
        tools["write"],
        "independent",
        {"path": "azents://execution/notes.md", "content": "notes"},
    )
    await invoke_consolidation_test_tool(
        tools["edit"],
        "edit",
        {"path": _URI, "old_string": "before", "new_string": "after"},
    )
    assert (await read_consolidation_test_uri(binding, _URI)).text == "after"
    await invoke_consolidation_test_tool(tools["delete"], "delete", {"path": _URI})
    with pytest.raises(VfsReadError):
        await read_consolidation_test_uri(binding, _URI)


async def test_unread_and_stale_same_target_mutations_are_correctable(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    first = binding.backend
    location = parse_vfs_exact_uri(_URI)
    create = VfsWriteRequest(location, "old", False)
    await binding.mutations.execute(
        binding.mutations.admit(binding.principal, create, tool_call_id="create")
    )
    first.observations.files.clear()
    edit = VfsEditRequest(location, "old", "new", False)
    with pytest.raises(VfsMutationError, match="Read"):
        await binding.mutations.execute(
            binding.mutations.admit(binding.principal, edit, tool_call_id="unread")
        )
    await read_consolidation_test_uri(binding, _URI)
    old = binding.mutations.admit(binding.principal, edit, tool_call_id="stale")
    await binding.bindings.files.write(
        binding.principal.owner, "summary.md", "other", "old", True
    )
    with pytest.raises(VfsMutationError, match="observation"):
        await binding.mutations.execute(old)
    assert (await read_consolidation_test_uri(binding, _URI)).text == "other"


@pytest.mark.parametrize("operation", ["write", "edit", "delete"])
async def test_provided_inputs_are_read_only(
    rdb_session_manager: SessionManager[WriteSession],
    operation: str,
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    uri = f"azents://execution/inputs/{binding.corpus.team_source}.md"
    source = await read_consolidation_test_uri(binding, uri)
    location = parse_vfs_exact_uri(uri)
    requests = {
        "write": VfsWriteRequest(location, "mutated", True),
        "edit": VfsEditRequest(location, source.text, "mutated", False),
        "delete": VfsDeleteRequest(location),
    }
    with pytest.raises(VfsMutationError, match="read-only"):
        await binding.mutations.execute(
            binding.mutations.admit(
                binding.principal, requests[operation], tool_call_id=operation
            )
        )
    assert (await read_consolidation_test_uri(binding, uri)).text == source.text


async def test_plain_inputs_search_glob_without_original_or_peer_mount(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    page = await binding.backend.glob(
        binding.principal,
        parse_vfs_glob_pattern("azents://execution/**"),
        exclude_patterns=(),
    )
    assert set(page.uris) == {
        "azents://execution/README.md",
        f"azents://execution/inputs/{binding.corpus.team_source}.md",
    }
    result = await binding.backend.grep(
        binding.principal,
        parse_vfs_search_uri("azents://execution/inputs"),
        pattern=re.compile("sentinel"),
        recursive=True,
        exclude_patterns=(),
        max_matching_files=10,
        max_lines_per_file=10,
        max_searched_files=10,
        max_scanned_bytes=20_000,
    )
    assert len(result.files) == 1
    for uri in (
        f"azents://execution/inputs/{binding.corpus.personal_source}.md",
        "azents://memory/sources/team/source/session.md",
        "azents://execution/original.jsonl",
    ):
        with pytest.raises(VfsReadError):
            await read_consolidation_test_uri(binding, uri)
    readme = await read_consolidation_test_uri(binding, "azents://execution/README.md")
    assert "submit_memory" in readme.text
    assert "coverage" not in readme.text and "work_id" not in readme.text


async def test_atomic_patch_and_applicability_failure_change_all_or_none(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    base = parse_vfs_search_uri("azents://execution")
    request = VfsAtomicPatchRequest(
        base,
        "*** Begin Patch\n*** Add File: summary.md\n+old\n"
        "*** Add File: notes.md\n+notes\n*** End Patch\n",
    )
    result = await binding.mutations.execute_patch(
        binding.mutations.admit_patch(binding.principal, request, tool_call_id="add")
    )
    assert result.file_count == 2
    await read_consolidation_test_uri(binding, _URI)
    await read_consolidation_test_uri(binding, "azents://execution/notes.md")
    update = VfsAtomicPatchRequest(
        base,
        "*** Begin Patch\n*** Update File: summary.md\n@@\n-old\n+new\n"
        "*** Delete File: notes.md\n*** End Patch\n",
    )
    admitted = binding.mutations.admit_patch(
        binding.principal, update, tool_call_id="update"
    )
    await binding.bindings.files.write(
        binding.principal.owner, "notes.md", "changed", "notes\n", True
    )
    with pytest.raises(VfsMutationError, match="applicability"):
        await binding.mutations.execute_patch(admitted)
    assert (await read_consolidation_test_uri(binding, _URI)).text == "old\n"
    await read_consolidation_test_uri(binding, "azents://execution/notes.md")
    result = await binding.mutations.execute_patch(
        binding.mutations.admit_patch(binding.principal, update, tool_call_id="retry")
    )
    assert (
        result.file_count == 1
        and (await read_consolidation_test_uri(binding, _URI)).text == "new\n"
    )
    with pytest.raises(VfsReadError):
        await read_consolidation_test_uri(binding, "azents://execution/notes.md")


async def test_stale_owner_cannot_read_or_mutate_private_files(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == binding.principal.owner.session_id)
            .values(owner_generation=RDBAgentSession.owner_generation + 1)
        )
    with pytest.raises(VfsReadError):
        await read_consolidation_test_uri(binding, "azents://execution/README.md")
    with pytest.raises(VfsMutationError):
        await binding.mutations.execute(
            binding.mutations.admit(
                binding.principal,
                VfsWriteRequest(parse_vfs_exact_uri(_URI), "no", False),
                tool_call_id="stale",
            )
        )
    forged = dataclasses.replace(
        binding.principal,
        owner=dataclasses.replace(binding.principal.owner, session_id="f" * 32),
    )
    with pytest.raises(VfsReadError):
        await binding.backend.glob(
            forged, parse_vfs_glob_pattern("azents://execution/**"), exclude_patterns=()
        )


async def test_atomic_patch_real_json_and_plaintext_tool_variants(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    tool = binding.tools({})["apply_patch"]
    assert isinstance(tool.handler, PlaintextCustomToolHandler)
    created = await invoke_consolidation_test_tool(
        tool,
        "json-add",
        {
            "base_path": "azents://execution",
            "patch": "*** Begin Patch\n*** Add File: summary.md\n+old\n*** End Patch\n",
        },
    )
    assert isinstance(created, FunctionToolResult)
    assert created.metadata["file_count"] == 1
    assert "revision_id" not in created.metadata
    await read_consolidation_test_uri(binding, _URI)
    with client_tool_execution_context(call_id="plain-update", name="apply_patch"):
        updated = await tool.handler.execute_plaintext_custom(
            "*** Base Path: azents://execution\n*** Begin Patch\n"
            "*** Update File: summary.md\n@@\n-old\n+new\n*** End Patch\n"
        )
    assert isinstance(updated, FunctionToolResult)
    assert updated.metadata["file_count"] == 1
    assert "revision" not in str(updated.output).lower()
    assert (await read_consolidation_test_uri(binding, _URI)).text == "new\n"


async def test_readonly_input_namespace_cannot_receive_new_authored_files(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    for uri in ("azents://execution/inputs/new.md", "azents://execution/README.md"):
        with pytest.raises(VfsMutationError, match="read-only"):
            binding.mutations.admit(
                binding.principal,
                VfsWriteRequest(parse_vfs_exact_uri(uri), "no", False),
                tool_call_id="reserved",
            )
