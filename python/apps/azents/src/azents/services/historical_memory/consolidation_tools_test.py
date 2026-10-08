"""Actual lowered closed catalogs, sibling observations and explicit feedback."""

import json

import pytest

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.engine.events.openai_responses import OpenAIResponsesRequest
from azents.engine.events.types import (
    ClientToolCallPayload,
    NativeArtifact,
    OutputTextPart,
    build_native_compat_key,
)
from azents.engine.provider_model_operation import prepare_model_operation_request
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.services.historical_memory.consolidation_tools import (
    ConsolidationToolBindings,
)
from azents.services.session_execution_files import ExecutionFileObservations
from azents.testing.consolidation_vfs import bind_consolidation_test_vfs
from azents.testing.model_selection import make_test_model_selection

_URI = "azents://execution/summary.md"


async def test_bindings_retain_the_injected_current_owner_observations(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    observations = ExecutionFileObservations(binding.principal.owner)
    observations.files[_URI] = "already observed"
    tools = ConsolidationToolBindings(
        binding.principal,
        binding.bindings.files,
        binding.bindings.executions,
        observations,
    )
    assert tools.observations is observations
    assert tools.observations.files[_URI] == "already observed"


async def test_sibling_mutations_do_not_inherit_each_others_observations(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    tools = binding.bindings
    selection = make_test_model_selection()
    create = tools.admit(
        [_call("create", "write", {"path": _URI, "content": "base"})], selection
    )[0]
    assert (await create.execute()).status == "completed"
    tools.merge(create)
    admitted = tools.admit(
        [
            _call(
                "first",
                "edit",
                {"path": _URI, "old_string": "base", "new_string": "one"},
            ),
            _call(
                "second",
                "edit",
                {"path": _URI, "old_string": "one", "new_string": "two"},
            ),
        ],
        selection,
    )
    assert (await admitted[0].execute()).status == "completed"
    tools.merge(admitted[0])
    second = await admitted[1].execute()
    assert second.status == "failed"
    assert any(
        "exact unambiguous context" in part.text
        for part in second.output
        if isinstance(part, OutputTextPart)
    )
    result = await tools.files.read(binding.principal.owner, "summary.md")
    assert result is not None and result.content == "one"


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.ANTHROPIC])
async def test_actual_lowered_catalog_has_only_current_files_and_path_only_submit(
    rdb_session_manager: SessionManager[WriteSession],
    provider: LLMProvider,
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    selection = make_test_model_selection(
        provider=provider,
        model_developer=(
            LLMModelDeveloper.OPENAI
            if provider is LLMProvider.OPENAI
            else LLMModelDeveloper.ANTHROPIC
        ),
    ).model_copy(
        update={
            "normalized_capabilities": ModelCapabilities(
                tool_calling=ModelToolCallingCapabilities(supported=True)
            )
        }
    )
    catalog = binding.bindings.catalog(
        selection, writer=binding.bindings.observations.snapshot()
    )
    request = prepare_model_operation_request(
        selection=selection,
        messages=[],
        catalog=catalog,
        system_prompt="Read azents://execution/README.md. Submit an authored result.",
        output_tokens=None,
    ).request
    if isinstance(request, OpenAIResponsesRequest):
        names = {tool["name"] for tool in request.tools}
    else:
        names = {tool.name for tool in request.parameters.function_tools}
    assert names == {"read", "grep", "glob", "write", "edit", "delete", "submit_memory"}
    assert catalog.active_toolkit_bindings == [] and catalog.deferred_tool_names == []
    schema = catalog.tools["submit_memory"].spec.input_schema
    properties = schema["properties"]
    assert isinstance(properties, dict) and set(properties) == {"path"}
    for call in [
        _call("runtime", "write", {"path": "/tmp/forbidden", "content": "no"}),
        _call("saved", "read", {"path": "azents://memory/saved/agent/forbidden.md"}),
        _call(
            "original",
            "read",
            {"path": "azents://memory/sources/team/forbidden/session.md"},
        ),
        _call("shell", "exec_command", {"command": "not executed"}),
    ]:
        result = await binding.bindings.admit([call], selection)[0].execute()
        assert result.status == "failed"


async def test_invalid_then_corrected_submit_keeps_same_execution_and_accepts_once(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    binding = await bind_consolidation_test_vfs(rdb_session_manager)
    tools = binding.bindings
    selection = make_test_model_selection()
    for uri in (
        "azents://execution/missing.md",
        f"azents://execution/inputs/{binding.corpus.team_source}.md",
    ):
        call = tools.admit([_call("bad", "submit_memory", {"path": uri})], selection)[0]
        result = await call.execute()
        assert result.status == "failed" and call.accepted is None
    create = tools.admit(
        [_call("create", "write", {"path": _URI, "content": "한" * 10_000})], selection
    )[0]
    assert (await create.execute()).status == "completed"
    tools.merge(create)
    oversized = tools.admit(
        [_call("size", "submit_memory", {"path": _URI})], selection
    )[0]
    feedback = await oversized.execute()
    assert feedback.status == "failed" and oversized.accepted is None
    assert "10,000" in str(feedback.output)
    corrected = tools.admit(
        [
            _call(
                "correct",
                "write",
                {
                    "path": _URI,
                    "content": "# Free-form\nUseful corrections.",
                    "overwrite": True,
                },
            )
        ],
        selection,
    )[0]
    assert (await corrected.execute()).status == "completed"
    tools.merge(corrected)
    submission = tools.admit(
        [_call("accepted", "submit_memory", {"path": _URI})], selection
    )[0]
    assert (await submission.execute()).status == "completed"
    assert submission.accepted is not None
    assert submission.accepted.session_id == binding.principal.owner.session_id
    replay = tools.admit(
        [_call("accepted", "submit_memory", {"path": _URI})], selection
    )[0]
    assert (await replay.execute()).status == "completed"
    assert replay.accepted == submission.accepted


def _call(
    call_id: str, name: str, arguments: dict[str, str | bool]
) -> ClientToolCallPayload:
    native = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="synthetic",
            native_format="test_output",
            provider="openai",
            model="gpt-4o",
            schema_version="1",
        ),
        adapter="synthetic",
        native_format="test_output",
        provider="openai",
        model="gpt-4o",
        schema_version="1",
        item={"type": "synthetic_tool_call"},
    )
    return ClientToolCallPayload(
        call_id=call_id,
        name=name,
        arguments=json.dumps(arguments),
        wire_dialect="json_function",
        native_artifact=native,
    )
