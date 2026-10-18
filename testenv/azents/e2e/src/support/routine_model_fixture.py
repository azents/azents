"""Deterministic Routine model rounds driven by actual returned product context."""

import json
import re
import threading
from dataclasses import dataclass
from typing import Literal

SETUP = "ROUTINE_E2E_SETUP"
READY = "ROUTINE_E2E_READY"
MARKER = "ROUTINE_E2E"
JOURNAL_PATH = "/v1/_routine_requests"
JUDGMENT_PREFIX = "Judge the supplied Session Routine candidates together."
CONTEXT_MARKER = "Admitted contexts:\n"
RUNTIME_PROOF = "ROUTINE_E2E_RUNTIME_PROOF"
UPDATE_PREFIX = "ROUTINE_E2E_UPDATE "
DELETE_PREFIX = "ROUTINE_E2E_DELETE "
UPDATED = "ROUTINE_E2E_UPDATED"
DELETED = "ROUTINE_E2E_DELETED"
UPDATED_OBJECTIVE = "ROUTINE_E2E updated objective from a fresh inspection."
HOLD = "ROUTINE_E2E_HOLD_ORDINARY_TOOL"
HOLD_DONE = "ROUTINE_E2E_HELD_TOOL_FINISHED"
CHANNEL_SETUP = "ROUTINE_E2E_CHANNEL_SETUP"
RUNTIME_BARRIER_PATH = "/v1/_routine_runtime_barrier"
HOLD_COMMAND = (
    'python -c "import urllib.request; '
    f"urllib.request.urlopen('http://openai-proxy:8081{RUNTIME_BARRIER_PATH}/wait',"
    " timeout=60).read(); "
    f"print('{RUNTIME_PROOF}')\""
)


class RuntimeBarrier:
    """Hold actual Runtime I/O until the test explicitly releases the boundary."""

    def __init__(self) -> None:
        self.armed = threading.Event()
        self.reached = threading.Event()
        self.released = threading.Event()

    def arm(self) -> None:
        self.reached.clear()
        self.released.clear()
        self.armed.set()

    def release(self) -> None:
        self.released.set()

    def wait(self) -> bool:
        if not self.armed.is_set():
            return True
        self.reached.set()
        return self.released.wait(timeout=60)

    def evidence(self) -> dict[str, bool]:
        return {
            "armed": self.armed.is_set(),
            "reached": self.reached.is_set(),
            "released": self.released.is_set(),
        }


@dataclass(frozen=True)
class ToolOutput:
    call_id: str
    text: str | None


@dataclass(frozen=True)
class Content:
    title: str
    objective: str
    sources: tuple[Literal["manual"], ...]

    def wire(self) -> dict[str, object]:
        """Serialize exact content read from the real inspection tool."""
        return {
            "title": self.title,
            "objective": self.objective,
            "sources": [{"type": source} for source in self.sources],
        }


@dataclass(frozen=True)
class Candidate:
    """Consumed immutable product fields; other context fields are extensions."""

    routine_id: str
    slug: str
    title: str
    objective: str
    previous_work: bool
    execution_id: str | None


@dataclass(frozen=True)
class Request:
    """A validated matching projection, separate from opaque provider wire."""

    latest_user: str
    completed_calls: tuple[str, ...]
    candidates: tuple[Candidate, ...]
    kind: Literal[
        "setup", "judgment", "work", "update", "delete", "hold", "channel_setup"
    ]
    title_request: bool
    tool_names: tuple[str, ...]
    structured: bool
    prior_text: tuple[str, ...]
    select_candidates: bool
    target_slug: str | None
    inspected_content: Content | None
    channel_binding: str | None


@dataclass(frozen=True)
class Text:
    response_id: str
    text: str


@dataclass(frozen=True)
class Call:
    call_id: str
    name: str
    arguments: dict[str, object]


def _record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError("Routine fixture requires an object.")
    return {key: child for key, child in value.items()}


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Routine fixture requires nonempty text.")
    return value


def _candidates(text: str, marker: str) -> tuple[Candidate, ...]:
    """Validate consumed product context once at the fixture ingress."""
    tail = text.partition(marker)[2]
    if not tail:
        raise ValueError("Routine context marker is absent.")
    raw, _ = json.JSONDecoder().raw_decode(tail)
    if not isinstance(raw, list) or not raw:
        raise ValueError("Routine candidate list is absent.")
    candidates: list[Candidate] = []
    for value in raw:
        item = _record(value)
        content = _record(item.get("content"))
        previous = item.get("latest_work")
        if previous is not None and not isinstance(previous, dict):
            raise ValueError("Routine previous work is invalid.")
        execution = item.get("execution_id")
        if execution is not None:
            execution = _text(execution)
        candidates.append(
            Candidate(
                routine_id=_text(item.get("routine_id")),
                slug=_text(item.get("slug")),
                title=_text(content.get("title")),
                objective=_text(content.get("objective")),
                previous_work=previous is not None,
                execution_id=execution,
            )
        )
    if len({item.routine_id for item in candidates}) != len(candidates):
        raise ValueError("Routine fixture candidate identities must be unique.")
    return tuple(candidates)


def is_judgment(text: str | None) -> bool:
    return text is not None and text.startswith(JUDGMENT_PREFIX) and MARKER in text


def _inspected_content(outputs: tuple[ToolOutput, ...], slug: str) -> Content | None:
    call_id = f"call_routine_e2e_inspect_{slug}"
    for output in outputs:
        if output.call_id != call_id:
            continue
        if output.text is None:
            raise ValueError("Routine inspection output is absent.")
        payload = _record(json.loads(output.text))
        definition = _record(_record(payload.get("routine")).get("definition"))
        if definition.get("slug") != slug:
            raise ValueError("Routine inspection returned another definition.")
        content = _record(definition.get("content"))
        if set(content) != {"title", "objective", "sources"}:
            raise ValueError("Routine inspection content has an unknown shape.")
        raw_sources = content["sources"]
        if not isinstance(raw_sources, list):
            raise ValueError("Routine inspection sources must be a list.")
        sources: list[Literal["manual"]] = []
        for source in raw_sources:
            if _record(source) != {"type": "manual"}:
                raise ValueError("Routine inspection source is unsupported.")
            sources.append("manual")
        return Content(
            title=_text(content["title"]),
            objective=_text(content["objective"]),
            sources=tuple(sources),
        )
    return None


def decode_request(
    *,
    latest_user: str | None,
    completed_calls: tuple[str, ...],
    tool_outputs: tuple[ToolOutput, ...],
    tool_names: tuple[str, ...],
    title_request: bool,
    prior_text: tuple[str, ...],
    wire_body: bytes,
) -> Request | None:
    """Match only Routine test input and decode Structured metadata at ingress."""
    if latest_user is None:
        return None
    candidates: tuple[Candidate, ...] = ()
    target_slug: str | None = None
    channel_binding: str | None = None
    if latest_user == SETUP:
        kind: Literal[
            "setup", "judgment", "work", "update", "delete", "hold", "channel_setup"
        ] = "setup"
    elif CHANNEL_SETUP in latest_user:
        binding = re.search(r"Binding: ([A-Za-z0-9_-]+)", latest_user)
        if binding is None and not title_request:
            raise ValueError("Routine channel setup requires actual Binding context.")
        channel_binding = None if binding is None else binding.group(1)
        kind = "channel_setup"
    elif latest_user == HOLD:
        kind = "hold"
    elif latest_user.startswith(UPDATE_PREFIX):
        kind = "update"
        target_slug = _text(latest_user.removeprefix(UPDATE_PREFIX))
    elif latest_user.startswith(DELETE_PREFIX):
        kind = "delete"
        target_slug = _text(latest_user.removeprefix(DELETE_PREFIX))
    elif is_judgment(latest_user):
        kind = "judgment"
        candidates = _candidates(latest_user, "Candidates:\n")
    elif CONTEXT_MARKER in latest_user and MARKER in latest_user:
        kind = "work"
        candidates = _candidates(latest_user, CONTEXT_MARKER)
        if any(item.execution_id is None for item in candidates):
            raise ValueError("Routine work must carry an admitted identity.")
    else:
        return None
    payload = _record(json.loads(wire_body))
    text = payload.get("text")
    formatting = _record(text).get("format") if isinstance(text, dict) else None
    structured = (
        isinstance(formatting, dict)
        and _record(formatting).get("type") == "json_schema"
    )
    return Request(
        latest_user=latest_user,
        completed_calls=completed_calls,
        candidates=candidates,
        kind=kind,
        title_request=title_request,
        tool_names=tool_names,
        structured=structured,
        prior_text=prior_text,
        select_candidates=False,
        target_slug=target_slug,
        inspected_content=(
            _inspected_content(tool_outputs, target_slug)
            if kind == "update" and target_slug is not None
            else None
        ),
        channel_binding=channel_binding,
    )


def evidence(request: Request) -> dict[str, object]:
    """Expose fake-test context and actual request shape, never auth headers."""
    return {
        "kind": request.kind,
        "candidate_ids": [item.routine_id for item in request.candidates],
        "candidate_objectives": [item.objective for item in request.candidates],
        "candidate_previous_work": [item.previous_work for item in request.candidates],
        "execution_ids": [item.execution_id for item in request.candidates],
        "tool_names": list(request.tool_names),
        "structured": request.structured,
        "setup_in_canonical_context": any(SETUP in text for text in request.prior_text),
        "completed_calls": list(request.completed_calls),
        "target_slug": request.target_slug,
    }


def plan(request: Request) -> Text | Call:
    """Select deterministic responses; every completion still executes real tools."""
    if request.title_request:
        return Text("resp_routine_e2e_title", '{"title":"Routine E2E"}')
    completed = set(request.completed_calls)
    if request.kind == "channel_setup":
        binding = request.channel_binding
        assert binding is not None
        search_id = f"call_routine_e2e_channel_search_{binding}"
        ignore_id = f"call_routine_e2e_channel_ignore_{binding}"
        if search_id not in completed:
            return Call(
                search_id, "tool_search", {"query": "channel_action", "limit": 1}
            )
        if ignore_id not in completed:
            return Call(
                ignore_id, "channel_action", {"mode": "ignore", "binding": binding}
            )
        return Text("resp_routine_e2e_channel_ready", "ROUTINE_E2E_CHANNEL_READY")
    if request.kind == "hold":
        if "call_routine_e2e_hold" not in completed:
            return Call(
                "call_routine_e2e_hold",
                "exec_command",
                {"command": HOLD_COMMAND, "yield_time_ms": 30000},
            )
        return Text("resp_routine_e2e_held", HOLD_DONE)
    if request.kind == "setup":
        for suffix, title in [("a", "ROUTINE_E2E Alpha"), ("b", "ROUTINE_E2E Beta")]:
            call_id = f"call_routine_e2e_create_{suffix}"
            if call_id not in completed:
                return Call(
                    call_id,
                    "create_routine",
                    {
                        "title": title,
                        "objective": (
                            f"ROUTINE_E2E {suffix}: check the local Runtime proof "
                            "once; retain a result."
                        ),
                        "sources": [{"type": "manual"}],
                    },
                )
        if "call_routine_e2e_list" not in completed:
            return Call("call_routine_e2e_list", "list_routines", {})
        return Text("resp_routine_e2e_ready", READY)
    if request.kind == "judgment":
        return Text(
            "resp_routine_e2e_judgment",
            json.dumps(
                {
                    "decisions": [
                        {
                            "routine_id": item.routine_id,
                            "act": request.select_candidates and not item.previous_work,
                        }
                        for item in request.candidates
                    ]
                }
            ),
        )
    if request.kind in {"update", "delete"}:
        slug = request.target_slug
        assert slug is not None
        if request.kind == "delete":
            call_id = f"call_routine_e2e_delete_{slug}"
            if call_id not in completed:
                return Call(call_id, "delete_routine", {"slug": slug})
            return Text(f"resp_routine_e2e_deleted_{slug}", DELETED)
        inspect_id = f"call_routine_e2e_inspect_{slug}"
        if inspect_id not in completed:
            return Call(
                inspect_id, "inspect_routine", {"slug": slug, "record_limit": 100}
            )
        content = request.inspected_content
        if content is None:
            raise ValueError("An actual current inspection is required for update.")
        stale_id = f"call_routine_e2e_stale_{slug}"
        if stale_id not in completed:
            return Call(
                stale_id,
                "update_routine",
                {
                    "slug": slug,
                    "expected": {**content.wire(), "objective": "STALE_CONTENT"},
                    "changes": {"objective": "MUST_NOT_APPLY"},
                },
            )
        update_id = f"call_routine_e2e_update_{slug}"
        if update_id not in completed:
            return Call(
                update_id,
                "update_routine",
                {
                    "slug": slug,
                    "expected": content.wire(),
                    "changes": {"objective": UPDATED_OBJECTIVE},
                },
            )
        return Text(f"resp_routine_e2e_updated_{slug}", UPDATED)
    first = request.candidates[0]
    execution = first.execution_id
    assert execution is not None
    command_id = f"call_routine_e2e_command_{execution}"
    if command_id not in completed:
        return Call(
            command_id,
            "exec_command",
            {
                "command": (
                    HOLD_COMMAND
                    if HOLD in request.prior_text
                    else f"printf '%s\\n' '{RUNTIME_PROOF}' > routine-e2e-proof.txt; "
                    "cat routine-e2e-proof.txt"
                ),
                "yield_time_ms": 30000,
            },
        )
    result_id = f"call_routine_e2e_result_{execution}"
    if result_id not in completed:
        notify = first.title.endswith("Beta")
        return Call(
            result_id,
            "record_routine_result",
            {
                "slug": first.slug,
                "execution_id": execution,
                "work": {
                    "objective_outcome": "failed" if notify else "finished",
                    "result": f"ROUTINE_E2E_RESULT_{first.title.rsplit(' ', 1)[-1]}",
                    "next_hint": (
                        "The single local check is complete; do not repeat it."
                    ),
                    "notify": notify,
                    "message": "ROUTINE_E2E_NOTIFICATION" if notify else None,
                },
            },
        )
    return Text(f"resp_routine_e2e_settled_{execution}", "ROUTINE_E2E_TURN_SETTLED")
