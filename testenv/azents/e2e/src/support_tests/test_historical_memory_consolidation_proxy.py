"""Pure multi-turn file-tool script and isolated provider-continuation contracts."""

import ast
import json
from collections import OrderedDict
from http.client import HTTPMessage
from pathlib import Path

import pytest

from support import image_generation_openai_proxy as proxy
from support.image_generation_openai_proxy import (
    ConsolidationFixtureContinuation,
    consolidation_fixture_plan,
    consolidation_fixture_request,
    historical_memory_summary_response,
    is_consolidation_fixture_request,
)

_CHAIN = "a" * 32
_SOURCE = "b" * 32
_URI = f"azents://execution/inputs/{_SOURCE}.md"
_MARKER = "AGENTIC_TEAM_OWN_V1"


def _current_host_instructions() -> str:
    """Read the product task as a contract fixture without importing its application."""
    module = (
        Path(__file__).resolve().parents[5]
        / "python/apps/azents/src/azents/services/historical_memory"
        / "consolidation_host.py"
    )
    for node in ast.parse(module.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_CONSOLIDATION_TASK"
            for target in node.targets
        ):
            value: object = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError("The current private Memory host task must be available.")


def _request() -> dict[str, object]:
    fields = {
        "read": {
            "path": "string",
            "offset": "integer",
            "limit": "integer",
            "encoding": "string",
        },
        "write": {"path": "string", "content": "string", "overwrite": "boolean"},
        "edit": {
            "path": "string",
            "old_string": "string",
            "new_string": "string",
            "replace_all": "boolean",
        },
        "glob": {"pattern": "string"},
        "grep": {"path": "string", "pattern": "string"},
        "delete": {"path": "string"},
        "submit_memory": {"path": "string"},
    }
    return {
        "model": "gpt-5.5",
        "instructions": _current_host_instructions(),
        "tools": [
            {
                "type": "function",
                "name": name,
                "description": f"Scoped execution file operation: {name}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        field: {"type": kind} for field, kind in parameters.items()
                    },
                    "additionalProperties": False,
                },
                "strict": False,
            }
            for name, parameters in fields.items()
        ]
        + [{"type": "custom", "name": "apply_patch", "format": {"type": "text"}}],
        "input": [],
        "stream": True,
    }


class _FixtureHandler(proxy._Handler):
    """Run HTTP dispatch without opening a listener or acquiring an upstream."""

    def __init__(self, request: dict[str, object]) -> None:
        self.path = "/v1/responses"
        self.headers = HTTPMessage()
        self.body = json.dumps(request).encode()
        self.call: proxy.ConsolidationFixtureCall | None = None

    def _read_body(self) -> bytes:
        return self.body

    def _write_function_call_response(
        self,
        request: proxy._ModelRequestInput,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        self.call = proxy.ConsolidationFixtureCall(call_id, name, arguments)

    def _write_json(self, status: int, value: object) -> None:
        raise AssertionError(f"Unexpected fixture HTTP status: {status}")

    def _proxy(self, body: bytes | None = None) -> None:
        raise AssertionError(
            "A current private Memory request must not reach upstream."
        )


def test_current_host_request_dispatches_file_script_without_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proxy._State, "requests", [])
    monkeypatch.setattr(proxy._State, "consolidation_continuations", OrderedDict())
    request = _request()
    assert is_consolidation_fixture_request(request)
    handler = _FixtureHandler(request)
    handler.do_POST()
    assert handler.call is not None and handler.call.name == "read"
    assert handler.call.arguments["path"] == "azents://execution/README.md"
    assert len(proxy._State.requests) == 1


def test_plain_file_rounds_require_submission_correction_and_continuation() -> None:
    """Provider plans request host effects rather than fabricate acceptance."""
    request = _request()
    inputs: list[dict[str, object]] = []
    request["input"] = inputs
    files: dict[str, str] = {}
    names: list[str] = []
    rejected = 0
    unsubmitted = 0
    for _round in range(20):
        plan = consolidation_fixture_plan(request, chain_id=_CHAIN)
        if plan.call is None:
            if plan.final_text == "CONSOLIDATION_FIXTURE_NOT_SUBMITTED":
                unsubmitted += 1
                inputs.append(
                    {
                        "role": "user",
                        "content": (
                            "The Memory task is not complete: "
                            "no explicit submission has been accepted."
                        ),
                    }
                )
                continue
            assert plan.final_text == (
                "CONSOLIDATION_FIXTURE_FINISHED_NOT_THE_PUBLICATION_BODY"
            )
            break
        call = plan.call
        names.append(call.name)
        if call.name == "glob":
            output = _URI
        else:
            path = call.arguments["path"]
            assert isinstance(path, str)
            if call.name == "read":
                if path == "azents://execution/README.md":
                    output = "Read inputs/*.md and submit the authored file."
                elif path == _URI:
                    output = (
                        f"{_MARKER}\nUser correction: use blue. Deployment unverified."
                    )
                else:
                    output = files.get(path, "Error: file is unavailable")
            elif call.name == "write":
                content = call.arguments["content"]
                assert isinstance(content, str)
                files[path] = content
                output = "File written"
            elif call.name == "submit_memory":
                assert set(call.arguments) == {"path"}
                if len(files[path].encode("utf-8")) > 10_000:
                    rejected += 1
                    output = "Submission exceeds the 10,000 UTF-8-byte allowance."
                else:
                    output = "Memory submission accepted."
            else:
                raise AssertionError(call.name)
        inputs.append(
            {"type": "function_call_output", "call_id": call.call_id, "output": output}
        )
    else:
        raise AssertionError("Fixture failed to complete bounded rounds")
    assert unsubmitted == 1 and rejected == 1
    assert names.count("submit_memory") == 2
    document = files["azents://execution/result.md"]
    assert _MARKER in document and "blue" in document and "unverified" in document
    assert "coverage.json" not in json.dumps(request)
    assert "memory-draft" not in json.dumps(request)
    assert "CONSOLIDATION_FIXTURE_FINISHED" not in document


def test_foreground_context_does_not_acquire_internal_script() -> None:
    request = _request()
    assert is_consolidation_fixture_request(request)
    tools = request["tools"]
    assert isinstance(tools, list)
    request["tools"] = [tool for tool in tools if tool["name"] != "submit_memory"] + [
        {"type": "function", "name": "save_memory"}
    ]
    assert not is_consolidation_fixture_request(request)
    request = _request()
    tools = request["tools"]
    assert isinstance(tools, list)
    request["tools"] = [tool for tool in tools if tool["name"] != "submit_memory"]
    assert not is_consolidation_fixture_request(request)


@pytest.mark.parametrize(
    "instructions",
    [
        "You are an internal historical-context consolidation Agent.",
        "You are an ordinary conversation Agent.",
        (
            "Quoted historical instructions follow: "
            "You are an internal historical-context Memory Agent."
        ),
    ],
)
def test_other_tasks_and_retired_marker_do_not_acquire_private_script(
    instructions: str,
) -> None:
    request = _request()
    request["instructions"] = instructions + "\n" + _current_host_instructions()
    assert not is_consolidation_fixture_request(request)


@pytest.mark.parametrize(
    "extra_tool",
    [
        {"type": "function", "name": "save_memory"},
        {"type": "function", "name": "exec_command"},
        {"type": "web_search"},
        {"type": "custom", "name": "runtime"},
        {"type": "function"},
        {"type": "function", "name": "read"},
    ],
)
def test_unknown_inherited_or_malformed_tools_reject_private_script(
    extra_tool: dict[str, object],
) -> None:
    request = _request()
    tools = request["tools"]
    assert isinstance(tools, list)
    tools.append(extra_tool)
    assert not is_consolidation_fixture_request(request)


@pytest.mark.parametrize("patch_kind", ["custom", "function"])
def test_current_closed_patch_wire_variant_is_permitted(patch_kind: str) -> None:
    request = _request()
    tools = request["tools"]
    assert isinstance(tools, list)
    patch = next(tool for tool in tools if tool["name"] == "apply_patch")
    patch["type"] = patch_kind
    if patch_kind == "function":
        patch.pop("format")
        patch["parameters"] = {
            "type": "object",
            "properties": {"input": {"type": "string"}},
        }
    assert is_consolidation_fixture_request(request)


def test_corrected_document_uses_only_supplied_summary_outputs() -> None:
    peer_marker = "AGENTIC_PERSONAL_UNSUPPLIED_V1"
    request = _request()
    outputs = {
        "readme": "Read the supplied summary files.",
        "inputs": _URI,
        "source0": f"{_MARKER}\nUser correction: blue; deployment unverified.",
        "write_oversized": "File written",
        "submit_oversized": "Submission exceeds the byte allowance.",
        "observe_result": "Oversized candidate",
    }
    request["input"] = [
        {
            "type": "function_call_output",
            "call_id": f"call_consolidation_{stage}_{_CHAIN}",
            "output": output,
        }
        for stage, output in outputs.items()
    ] + [
        {
            "role": "user",
            "content": (
                "The Memory task is not complete: no explicit submission has been "
                f"accepted. Unrelated unfinished context: {peer_marker}."
            ),
        }
    ]
    plan = consolidation_fixture_plan(request, chain_id=_CHAIN)
    assert plan.call is not None and plan.call.name == "write"
    document = plan.call.arguments["content"]
    assert isinstance(document, str)
    assert _MARKER in document and peer_marker not in document


def test_provider_continuation_keeps_own_chain_and_rejects_retired_state() -> None:
    first = _request()
    first["input"] = [{"role": "user", "content": "Own execution"}]
    result = consolidation_fixture_request(first, {}, new_chain_id=_CHAIN)
    assert result.chain_id == _CHAIN
    identifier = f"resp_consolidation_readme_{_CHAIN}"
    prior = ConsolidationFixtureContinuation(
        _CHAIN, [{"role": "user", "content": "Own execution"}]
    )
    next_request = {
        **first,
        "previous_response_id": identifier,
        "input": [
            {
                "type": "function_call_output",
                "call_id": f"call_consolidation_readme_{_CHAIN}",
                "output": "Own input instructions",
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
        "instructions": (
            "Create a bounded, self-contained historical account "
            "from the source Session."
        ),
    }
    response = historical_memory_summary_response(request)
    assert response is not None and _MARKER in response
    assert "AGENTIC_PERSONAL" not in response
