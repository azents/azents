"""Pure multi-turn file-tool script and isolated provider-continuation contracts."""

import json

import pytest

from support.image_generation_openai_proxy import (
    ConsolidationFixtureContinuation,
    consolidation_fixture_plan,
    consolidation_fixture_request,
    historical_memory_summary_response,
    is_consolidation_fixture_request,
)

_CHAIN = "a" * 32
_SOURCE = "b" * 32
_WORK = "c" * 32
_URI = f"azents://memory/historical/team/{_SOURCE}/summary.md"
_MARKER = "AGENTIC_TEAM_OWN_V1"


def _request() -> dict[str, object]:
    return {
        "instructions": "You are an internal historical-context consolidation Agent.",
        "tools": [
            {"name": name}
            for name in ("read", "write", "edit", "glob", "grep", "delete")
        ],
        "input": [],
    }


@pytest.mark.parametrize("source_epoch_conflict", [False, True])
def test_real_rounds_depend_on_results_and_publish_no_final_text_payload(
    source_epoch_conflict: bool,
) -> None:
    request = _request()
    inputs: list[dict[str, object]] = []
    request["input"] = inputs
    files: dict[str, str] = {}
    names: list[str] = []
    failed_edits = 0
    for _round in range(20):
        plan = consolidation_fixture_plan(request, chain_id=_CHAIN)
        if plan.call is None:
            assert (
                plan.final_text
                == "CONSOLIDATION_FIXTURE_FINISHED_NOT_THE_PUBLICATION_BODY"
            )
            break
        call = plan.call
        names.append(call.name)
        path = call.arguments["path"]
        assert isinstance(path, str)
        if call.name == "read":
            if path == "azents://memory/inventory/work/README.md":
                output = (
                    "# Pending source changes\n"
                    f"- Work {_WORK}; prepared; {_URI} — Own source\n"
                )
            elif path == _URI:
                output = f"{_MARKER}\nUser correction: use blue. Deployment unverified."
            else:
                output = files.get(path, "Error: VFS file is unavailable")
        elif call.name == "write":
            content = call.arguments["content"]
            assert isinstance(content, str)
            if source_epoch_conflict and call.call_id.startswith(
                "call_consolidation_write_summary_"
            ):
                output = "VFS source read evidence changed."
            else:
                files[path] = content
                output = "VFS write committed: synthetic fixture"
        elif call.name == "edit":
            old, new = call.arguments["old_string"], call.arguments["new_string"]
            assert isinstance(old, str) and isinstance(new, str)
            if files[path].count(old) != 1:
                failed_edits += 1
                output = "Error: exact edit match is unavailable"
            else:
                files[path] = files[path].replace(old, new)
                output = "File edited"
        else:
            raise AssertionError(call.name)
        inputs.append(
            {"type": "function_call_output", "call_id": call.call_id, "output": output}
        )
    else:
        raise AssertionError("Fixture failed to complete bounded rounds")
    assert names.count("read") >= 6 and names.count("edit") == 2
    assert failed_edits == 1
    document = files["azents://memory-draft/summary.md"]
    assert _MARKER in document and "Source-dependent integrated context" in document
    assert "CONSOLIDATION_FIXTURE_FINISHED" not in document
    assert _URI in document and "## Source Routes" in document
    coverage = json.loads(files["azents://memory-draft/coverage.json"])
    assert coverage["dispositions"] == [
        {
            "work_id": _WORK,
            "action": "considered",
            "reason": "Integrated source-dependent evidence",
        }
    ]


def test_mixed_scopes_and_foreground_context_do_not_acquire_internal_script() -> None:
    request = _request()
    assert is_consolidation_fixture_request(request)
    request["tools"] = [
        {"name": name} for name in ("read", "write", "edit", "save_memory")
    ]
    assert not is_consolidation_fixture_request(request)
    request = _request()
    request["input"] = [
        {
            "type": "function_call_output",
            "call_id": f"call_consolidation_work_{_CHAIN}",
            "output": (
                f"- Work {_WORK}; prepared; {_URI} — Team\n"
                f"- Work {'d' * 32}; prepared; "
                f"azents://memory/historical/user/{'e' * 32}/summary.md — Personal\n"
            ),
        }
    ]
    with pytest.raises(ValueError, match="scope boundary"):
        consolidation_fixture_plan(request, chain_id=_CHAIN)


def test_provider_continuation_keeps_own_chain_and_rejects_retired_state() -> None:
    first = _request()
    first["input"] = [{"role": "user", "content": "Own execution"}]
    result = consolidation_fixture_request(first, {}, new_chain_id=_CHAIN)
    assert result.chain_id == _CHAIN
    identifier = f"resp_consolidation_work_{_CHAIN}"
    prior = ConsolidationFixtureContinuation(
        _CHAIN, [{"role": "user", "content": "Own execution"}]
    )
    next_request = {
        **first,
        "previous_response_id": identifier,
        "input": [
            {
                "type": "function_call_output",
                "call_id": f"call_consolidation_work_{_CHAIN}",
                "output": "Own inventory",
            }
        ],
    }
    continued = consolidation_fixture_request(
        next_request, {identifier: prior}, new_chain_id="f" * 32
    )
    assert continued.chain_id == _CHAIN
    inputs = continued.request["input"]
    assert isinstance(inputs, list) and len(inputs) == 2
    with pytest.raises(ValueError, match="unavailable"):
        consolidation_fixture_request(next_request, {}, new_chain_id="f" * 32)


def test_stage1_keeps_only_this_request_synthetic_scope_markers() -> None:
    request: dict[str, object] = {
        "input": [
            {"role": "user", "content": f"Historical Memory E2E source {_MARKER}"}
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "historical_memory",
                "strict": True,
                "schema": {
                    "additionalProperties": False,
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                },
            }
        },
    }
    response = historical_memory_summary_response(request)
    assert response is not None and _MARKER in response
    assert "AGENTIC_PERSONAL" not in response
