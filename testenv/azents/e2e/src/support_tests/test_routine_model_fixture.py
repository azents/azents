"""Docker-free parser and response contracts for the real Routine E2E model."""

import json
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from support import image_generation_openai_proxy as proxy
from support import routine_model_fixture as fixture


def _candidate(identity: str, *, previous: bool, execution: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "routine_id": identity,
        "slug": identity,
        "content": {
            "title": f"ROUTINE_E2E {identity}",
            "objective": f"ROUTINE_E2E original {identity}",
            "sources": [{"type": "manual"}],
        },
        "events": [{"source_type": "manual", "observed_at": "2099-01-01T00:00:00Z"}],
        "latest_work": {"result": "previous"} if previous else None,
        "last_executed_at": None,
    }
    if execution:
        value["execution_id"] = f"execution-{identity}"
    return value


def _request(text: str, *, completed: tuple[str, ...] = ()) -> fixture.Request:
    request = fixture.decode_request(
        latest_user=text,
        completed_calls=completed,
        tool_outputs=(),
        tool_names=(),
        title_request=False,
        prior_text=(fixture.SETUP, text),
        wire_body=b'{"text":{"format":{"type":"json_schema"}}}',
    )
    assert request is not None
    return request


def test_setup_creates_real_tools_then_observes_product_inventory() -> None:
    completed: tuple[str, ...] = ()
    for name in ["create_routine", "create_routine", "list_routines"]:
        plan = fixture.plan(_request(fixture.SETUP, completed=completed))
        assert isinstance(plan, fixture.Call) and plan.name == name
        completed += (plan.call_id,)
    final = fixture.plan(_request(fixture.SETUP, completed=completed))
    assert isinstance(final, fixture.Text) and final.text == fixture.READY


def test_joint_judgment_uses_product_identity_previous_work_and_structured_shape() -> (
    None
):
    text = (
        fixture.JUDGMENT_PREFIX
        + "\nCandidates:\n"
        + json.dumps(
            [
                _candidate("a", previous=False, execution=False),
                _candidate("b", previous=True, execution=False),
            ]
        )
    )
    request = _request(text)
    deferred = fixture.plan(request)
    assert isinstance(deferred, fixture.Text)
    assert all(not item["act"] for item in json.loads(deferred.text)["decisions"])
    plan = fixture.plan(replace(request, select_candidates=True))
    assert isinstance(plan, fixture.Text)
    assert json.loads(plan.text) == {
        "decisions": [
            {"routine_id": "a", "act": True},
            {"routine_id": "b", "act": False},
        ]
    }
    evidence = fixture.evidence(request)
    assert evidence["candidate_ids"] == ["a", "b"]
    assert evidence["tool_names"] == []
    assert evidence["structured"] is True
    assert evidence["setup_in_canonical_context"] is True


def test_timing_first_prompt_with_current_time_is_a_judgment_request() -> None:
    text = (
        "Decide whether to start work now for each Session\nRoutine candidate.\n"
        "Current time: 2026-10-19T09:58:00+00:00\n\nCandidates:\n"
        + json.dumps([_candidate("a", previous=False, execution=False)])
    )
    request = _request(text)
    assert request.kind == "judgment"
    assert request.structured
    result = fixture.plan(request)
    assert isinstance(result, fixture.Text)
    assert json.loads(result.text) == {"decisions": [{"routine_id": "a", "act": False}]}


def test_work_runs_runtime_then_completes_only_one_admitted_occurrence() -> None:
    text = (
        "Continue work.\n"
        + fixture.CONTEXT_MARKER
        + json.dumps(
            [
                _candidate("Alpha", previous=False, execution=True),
                _candidate("Beta", previous=False, execution=True),
            ]
        )
    )
    request = _request(text)
    command = fixture.plan(request)
    assert isinstance(command, fixture.Call) and command.name == "exec_command"
    assert fixture.RUNTIME_PROOF in str(command.arguments["command"])
    request = _request(text, completed=(command.call_id,))
    result = fixture.plan(request)
    assert isinstance(result, fixture.Call) and result.name == "record_routine_result"
    assert result.arguments["execution_id"] == "execution-Alpha"
    assert result.arguments["work"] == {
        "objective_outcome": "finished",
        "result": "ROUTINE_E2E_RESULT_Alpha",
        "next_hint": "The single local check is complete; do not repeat it.",
        "notify": False,
        "message": None,
    }
    final = fixture.plan(_request(text, completed=(command.call_id, result.call_id)))
    assert isinstance(final, fixture.Text)
    continuation = (
        "Continue work.\n"
        + fixture.CONTEXT_MARKER
        + json.dumps(
            [
                _candidate("Beta", previous=False, execution=True),
            ]
        )
    )
    second_command = fixture.plan(_request(continuation))
    assert isinstance(second_command, fixture.Call)
    second = fixture.plan(_request(continuation, completed=(second_command.call_id,)))
    assert isinstance(second, fixture.Call)
    assert second.arguments["work"] == {
        "objective_outcome": "failed",
        "result": "ROUTINE_E2E_RESULT_Beta",
        "next_hint": "The single local check is complete; do not repeat it.",
        "notify": True,
        "message": "ROUTINE_E2E_NOTIFICATION",
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        [{"routine_id": "bad"}],
        [
            _candidate("a", previous=False, execution=False),
            _candidate("a", previous=False, execution=False),
        ],
    ],
)
def test_malformed_candidates_never_become_synthetic_no_action(payload: object) -> None:
    text = fixture.JUDGMENT_PREFIX + " ROUTINE_E2E\nCandidates:\n" + json.dumps(payload)
    with pytest.raises(ValueError):
        _request(text)


def test_non_routine_request_is_not_decoded_or_intercepted() -> None:
    assert (
        fixture.decode_request(
            latest_user="Unrelated request",
            completed_calls=(),
            tool_outputs=(),
            tool_names=(),
            title_request=False,
            prior_text=(),
            wire_body=b"not JSON",
        )
        is None
    )


def test_only_judgment_receives_distinct_usage() -> None:
    handler = object.__new__(proxy._Handler)
    for text, total in [
        ("ordinary", 2),
        (fixture.JUDGMENT_PREFIX + " ROUTINE_E2E", 99999),
    ]:
        response = handler._response(
            request={"input": [{"role": "user", "content": text}]},
            response_id="resp_fixture",
            model="fixture",
            output=[],
        )
        usage = response["usage"]
        assert isinstance(usage, dict)
        assert usage["total_tokens"] == total


def test_native_delta_uses_only_its_recorded_fixture_response_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider stored-response reduction must not erase the setup user input."""
    monkeypatch.setattr(proxy._State, "routine_continuations", OrderedDict())
    monkeypatch.setattr(proxy._State, "routine_requests", [])
    handler = object.__new__(proxy._Handler)
    first: dict[str, object] = {"input": [{"role": "user", "content": fixture.SETUP}]}
    handler._response(
        request=first,
        response_id="resp_routine_e2e_create_a",
        model="fixture",
        output=[
            {
                "type": "function_call",
                "call_id": "call_routine_e2e_create_a",
                "name": "create_routine",
                "arguments": "{}",
            }
        ],
    )
    captured: list[fixture.Call] = []

    def capture(
        request: proxy._ModelRequestInput,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        captured.append(fixture.Call(call_id, name, arguments))

    monkeypatch.setattr(handler, "_write_function_call_response", capture)
    delta: dict[str, object] = {
        "previous_response_id": "resp_routine_e2e_create_a",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "call_routine_e2e_create_a",
                "output": "{}",
            }
        ],
    }
    handler._dispatch_model_request(delta, json.dumps(delta).encode())
    assert len(captured) == 1 and captured[0].call_id == "call_routine_e2e_create_b"


def test_first_check_defers_and_repeated_physical_request_keeps_its_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a new source opportunity advances the deterministic choice round."""
    monkeypatch.setattr(proxy._State, "routine_judgment_rounds", {})
    monkeypatch.setattr(proxy._State, "routine_judgment_choices", {})
    monkeypatch.setattr(proxy._State, "routine_requests", [])
    handler = object.__new__(proxy._Handler)
    captured: list[str] = []

    def capture(
        request: proxy._ModelRequestInput, text: str, *, response_id: str
    ) -> None:
        captured.append(text)

    monkeypatch.setattr(handler, "_write_text_response", capture)
    for instant in [
        "2099-01-01T00:00:00Z",
        "2099-01-01T00:00:00Z",
        "2099-01-01T00:30:00Z",
    ]:
        candidate = _candidate("a", previous=False, execution=False)
        candidate["events"] = [{"source_type": "manual", "observed_at": instant}]
        text = fixture.JUDGMENT_PREFIX + "\nCandidates:\n" + json.dumps([candidate])
        payload: dict[str, object] = {
            "input": [{"role": "user", "content": text}],
            "text": {"format": {"type": "json_schema"}},
        }
        handler._dispatch_model_request(payload, json.dumps(payload).encode())
    assert [json.loads(text)["decisions"][0]["act"] for text in captured] == [
        False,
        False,
        True,
    ]


def test_update_uses_inspection_and_separates_stale_and_exact_inputs() -> None:
    slug = "routine-owned"
    inspect_id = f"call_routine_e2e_inspect_{slug}"
    stale_id = f"call_routine_e2e_stale_{slug}"
    content = {
        "title": "Original title",
        "objective": "Original objective",
        "sources": [{"type": "manual"}],
    }

    def request(completed: tuple[str, ...], *, inspected_slug: str) -> fixture.Request:
        decoded = fixture.decode_request(
            latest_user=fixture.UPDATE_PREFIX + slug,
            completed_calls=completed,
            tool_outputs=(
                fixture.ToolOutput(
                    inspect_id,
                    json.dumps(
                        {
                            "routine": {
                                "definition": {
                                    "slug": inspected_slug,
                                    "content": content,
                                },
                                "records": [],
                            },
                        }
                    ),
                ),
            )
            if inspect_id in completed
            else (),
            tool_names=(),
            title_request=False,
            prior_text=(),
            wire_body=b"{}",
        )
        assert decoded is not None
        return decoded

    inspect = fixture.plan(request((), inspected_slug=slug))
    assert isinstance(inspect, fixture.Call) and inspect.name == "inspect_routine"
    stale = fixture.plan(request((inspect_id,), inspected_slug=slug))
    assert isinstance(stale, fixture.Call)
    assert stale.arguments["expected"] == {**content, "objective": "STALE_CONTENT"}
    actual = fixture.plan(request((inspect_id, stale_id), inspected_slug=slug))
    assert isinstance(actual, fixture.Call)
    assert actual.arguments["expected"] == content
    assert actual.arguments["changes"] == {"objective": fixture.UPDATED_OBJECTIVE}
    with pytest.raises(ValueError, match="another definition"):
        request((inspect_id,), inspected_slug="foreign")


def test_runtime_barrier_uses_explicit_reach_release_and_rearm() -> None:
    barrier = fixture.RuntimeBarrier()
    assert barrier.wait()
    with ThreadPoolExecutor(max_workers=1) as pool:
        for _ in range(2):
            barrier.arm()
            assert barrier.evidence() == {
                "armed": True,
                "reached": False,
                "released": False,
            }
            future = pool.submit(barrier.wait)
            try:
                assert barrier.reached.wait(timeout=5)
                assert not future.done()
            finally:
                barrier.release()
            assert future.result(timeout=5)
            assert barrier.evidence()["released"]


def test_held_ordinary_tool_and_selected_work_use_the_same_runtime_barrier() -> None:
    ordinary = fixture.plan(_request(fixture.HOLD))
    assert isinstance(ordinary, fixture.Call)
    assert ordinary.arguments == {
        "command": fixture.HOLD_COMMAND,
        "yield_time_ms": 30000,
    }
    finished = fixture.plan(_request(fixture.HOLD, completed=(ordinary.call_id,)))
    assert isinstance(finished, fixture.Text) and finished.text == fixture.HOLD_DONE
    work = _request(
        fixture.CONTEXT_MARKER
        + json.dumps([_candidate("Alpha", previous=False, execution=True)])
    )
    selected = fixture.plan(replace(work, prior_text=(fixture.HOLD,)))
    assert isinstance(selected, fixture.Call)
    assert fixture.RUNTIME_BARRIER_PATH in str(selected.arguments["command"])


def test_channel_setup_finishes_ordinary_work_before_routine_checks() -> None:
    request = _request(f"Binding: binding-owned\n{fixture.CHANNEL_SETUP}")
    search = fixture.plan(request)
    assert isinstance(search, fixture.Call) and search.name == "tool_search"
    ignore = fixture.plan(replace(request, completed_calls=(search.call_id,)))
    assert isinstance(ignore, fixture.Call)
    assert ignore.name == "channel_action"
    assert ignore.arguments == {"mode": "ignore", "binding": "binding-owned"}
    settled = fixture.plan(
        replace(request, completed_calls=(search.call_id, ignore.call_id))
    )
    assert isinstance(settled, fixture.Text)
    with pytest.raises(ValueError, match="Binding context"):
        _request(fixture.CHANNEL_SETUP)
