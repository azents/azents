"""Atomic private V4A through both real tool dialects without Runtime fallback."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.core.vfs import parse_vfs_search_uri
from azents.engine.events.tools import (
    ToolCatalog,
    project_tool_catalog_for_client_compatibility,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
)
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
    PlaintextCustomToolHandler,
)
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tooling.tool_search import (
    CatalogTool,
    ToolCatalogSource,
    ToolExposure,
)
from azents.rdb.session import SessionManager
from azents.services.vfs_mutation import VfsAtomicPatchRequest, VfsMutationError
from azents.services.vfs_read import VfsReadError
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


async def test_private_atomic_patch_both_wire_variants_and_result_loss(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    patch_tool = tools["apply_patch"]
    assert isinstance(patch_tool.handler, PlaintextCustomToolHandler)
    add = (
        "*** Begin Patch\n*** Add File: summary.md\n+old\n"
        "*** Add File: notes.md\n+notes\n*** End Patch\n"
    )
    result = await _invoke(
        patch_tool,
        "add-patch",
        {
            "base_path": "azents://memory-draft",
            "patch": add,
        },
    )
    assert isinstance(result, FunctionToolResult)
    assert result.metadata["file_count"] == 2
    assert (
        await _invoke(
            patch_tool,
            "add-patch",
            {
                "base_path": "azents://memory-draft",
                "patch": add,
            },
        )
        == result
    )
    await _read(binding, _URI)
    await _read(binding, "azents://memory-draft/notes.md")
    patch = (
        "*** Begin Patch\n*** Update File: summary.md\n@@\n-old\n+new\n"
        "*** Delete File: notes.md\n*** End Patch\n"
    )
    with client_tool_execution_context(call_id="custom-patch", name="apply_patch"):
        changed = await patch_tool.handler.execute_plaintext_custom(
            "*** Base Path: azents://memory-draft\n" + patch
        )
    assert isinstance(changed, FunctionToolResult)
    assert changed.metadata["file_count"] == 1
    assert (await _read(binding, _URI)).text == "new\n"
    with pytest.raises(VfsReadError):
        await _read(binding, "azents://memory-draft/notes.md")
    with client_tool_execution_context(call_id="custom-patch", name="apply_patch"):
        assert (
            await patch_tool.handler.execute_plaintext_custom(
                "*** Base Path: azents://memory-draft\n" + patch
            )
            == changed
        )


async def test_patch_applicability_failure_changes_no_file_or_revision(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "first", {"path": _URI, "content": "old\n"})
    await _invoke(
        tools["write"],
        "second",
        {
            "path": "azents://memory-draft/notes.md",
            "content": "notes\n",
        },
    )
    await _read(binding, _URI)
    await _read(binding, "azents://memory-draft/notes.md")
    before = await binding.draft.repository.observe(
        binding.principal, path="summary.md"
    )
    patch = (
        "*** Begin Patch\n*** Update File: summary.md\n@@\n-old\n+new\n"
        "*** Update File: notes.md\n@@\n-missing\n+replaced\n*** End Patch\n"
    )
    with pytest.raises(FunctionToolError, match="not found exactly"):
        await _invoke(
            tools["apply_patch"],
            "invalid-context",
            {
                "base_path": "azents://memory-draft",
                "patch": patch,
            },
        )
    after = await binding.draft.repository.observe(binding.principal, path="summary.md")
    assert after.draft_revision_id == before.draft_revision_id
    assert after.content == "old\n"
    assert (await _read(binding, "azents://memory-draft/notes.md")).text == "notes\n"


@pytest.mark.parametrize(
    "target", ["/tmp/runtime", "../escape", "azents://memory/other"]
)
async def test_mixed_patch_targets_reject_before_native_runtime(
    rdb_session_manager: SessionManager[AsyncSession], target: str
) -> None:
    binding = await _binding(rdb_session_manager)
    runtime = AsyncMock(return_value="unexpected native call")
    native = FunctionTool(
        FunctionToolSpec(name="apply_patch", description="native", input_schema={}),
        runtime,
    )
    tools = binding.tools({"apply_patch": native})
    patch = (
        "*** Begin Patch\n*** Add File: allowed.md\n+first\n"
        f"*** Add File: {target}\n+second\n*** End Patch\n"
    )
    with pytest.raises(FunctionToolError):
        await _invoke(
            tools["apply_patch"],
            "mixed",
            {
                "base_path": "azents://memory-draft",
                "patch": patch,
            },
        )
    runtime.assert_not_awaited()
    assert await binding.draft.repository.inventory(binding.principal) == ()


async def test_queued_patch_rejects_delete_recreate_aba(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "old\n"})
    await _read(binding, _URI)
    request = VfsAtomicPatchRequest(
        parse_vfs_search_uri("azents://memory-draft"),
        "*** Begin Patch\n*** Update File: summary.md\n@@\n-old\n+new\n*** End Patch\n",
    )
    admitted = binding.mutations.admit_patch(
        binding.principal, request, tool_call_id="old-ticket"
    )
    await _invoke(tools["delete"], "delete", {"path": _URI})
    with pytest.raises(VfsReadError):
        await _read(binding, _URI)
    await _invoke(tools["write"], "recreate", {"path": _URI, "content": "old\n"})
    await _read(binding, _URI)
    with pytest.raises(VfsMutationError, match="stale"):
        await binding.mutations.execute_patch(admitted)
    assert (await _read(binding, _URI)).text == "old\n"


async def test_patch_existing_target_requires_read_before_applicability(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    await _invoke(tools["write"], "create", {"path": _URI, "content": "old\n"})
    with pytest.raises(FunctionToolError, match="Read every existing"):
        await _invoke(
            tools["apply_patch"],
            "unread",
            {
                "base_path": "azents://memory-draft",
                "patch": (
                    "*** Begin Patch\n*** Delete File: summary.md\n*** End Patch\n"
                ),
            },
        )
    assert (await _read(binding, _URI)).text == "old\n"


async def test_model_without_v4a_keeps_all_required_ordinary_mutations(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    binding = await _binding(rdb_session_manager)
    tools = binding.tools({})
    source = ToolCatalogSource(
        slug="internal-memory",
        namespace="internal-memory",
        toolkit_type=None,
        toolkit_class="ConsolidationFiles",
        display_name="Consolidation files",
        use_prefix=False,
    )
    candidate = ToolCatalog(
        tools=tools,
        wire_dialects={},
        entries={
            name: CatalogTool(tool, source, ToolExposure.DIRECT)
            for name, tool in tools.items()
        },
        static_prompt_fragment_inputs=[],
        dynamic_prompt_fragment_inputs=[],
        active_toolkit_bindings=[],
    )
    adapter = resolve_client_tool_adapter_profile(
        route=ClientToolRoute(LLMProvider.OPENAI, "openai", "responses")
    )
    assert adapter is not None
    compatible = project_tool_catalog_for_client_compatibility(
        candidate, frozenset(), adapter
    )
    assert set(compatible.tools) == {"write", "edit", "delete"}
