"""Prove independent Brave admissions always drain before assertions continue."""

import pytest
import requests

from tests.required.public import test_brave_search as brave


@pytest.mark.parametrize("submit_failure", [None, "news"])
@pytest.mark.parametrize("drain_failure", [False, True])
def test_batch_admits_before_waiting_and_drains_after_failures(
    monkeypatch: pytest.MonkeyPatch,
    submit_failure: str | None,
    drain_failure: bool,
) -> None:
    created: list[str] = []
    submitted: list[str] = []
    drained: list[str] = []
    trace: list[str] = []

    def create(*, server_url: str, token: str, agent_id: str) -> str:
        assert (server_url, token, agent_id) == ("server", "token", "agent")
        session_id = f"session-{len(created)}"
        created.append(session_id)
        trace.append(f"create:{session_id}")
        return session_id

    def submit(
        *, server_url: str, token: str, agent_id: str, session_id: str, kind: str
    ) -> None:
        submitted.append(kind)
        trace.append(f"submit:{session_id}")
        if kind == submit_failure:
            raise RuntimeError("submission failed")

    def drain(*, server_url: str, token: str, agent_id: str, session_id: str) -> None:
        drained.append(session_id)
        trace.append(f"drain:{session_id}")
        if drain_failure and len(drained) == 1:
            raise RuntimeError("drain failed")

    monkeypatch.setattr(brave, "_create_profile_session", create)
    monkeypatch.setattr(brave, "_submit", submit)
    monkeypatch.setattr(brave, "_wait_for_terminal_session", drain)
    if submit_failure or drain_failure:
        with pytest.raises(RuntimeError):
            brave._completed_success_sessions(
                server_url="server", token="token", agent_id="agent"
            )
    else:
        result = brave._completed_success_sessions(
            server_url="server", token="token", agent_id="agent"
        )
        assert tuple(result) == brave._KINDS
        assert tuple(result.values()) == tuple(created)

    assert created
    assert drained == list(reversed(created))
    assert submitted == list(brave._KINDS[: len(created)])
    first_drain = next(i for i, event in enumerate(trace) if event.startswith("drain:"))
    assert all(
        event.startswith(("create:", "submit:")) for event in trace[:first_drain]
    )
    assert all(event.startswith("drain:") for event in trace[first_drain:])


def test_terminal_drain_requires_marker_before_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projections: list[list[dict[str, object]]] = [
        [],
        [{"kind": "run_marker", "payload": {"status": "failed"}}],
    ]
    trace: list[str] = []

    def events(
        *, server_url: str, token: str, session_id: str
    ) -> list[dict[str, object]]:
        trace.append("history")
        return projections.pop(0)

    def idle(*, server_url: str, token: str, agent_id: str, session_id: str) -> None:
        trace.append("idle")

    def interval(seconds: float) -> None:
        assert seconds == 0.2
        trace.append("poll")

    monkeypatch.setattr(brave, "_tool_events", events)
    monkeypatch.setattr(brave, "_wait_for_idle", idle)
    monkeypatch.setattr(brave.time, "sleep", interval)
    brave._wait_for_terminal_session(
        server_url="server", token="token", agent_id="agent", session_id="session"
    )
    assert trace == ["history", "poll", "history", "idle"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 500])
def test_rejection_preserves_http_error_and_drains_previously_admitted_sessions(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    created: list[str] = []
    drained: list[str] = []
    response = requests.Response()
    response.status_code = status
    rejection = requests.HTTPError("input rejected", response=response)

    def create(*, server_url: str, token: str, agent_id: str) -> str:
        session_id = f"session-{len(created)}"
        created.append(session_id)
        return session_id

    def submit(
        *, server_url: str, token: str, agent_id: str, session_id: str, kind: str
    ) -> None:
        if kind == "news":
            raise rejection

    def events(
        *, server_url: str, token: str, session_id: str
    ) -> list[dict[str, object]]:
        drained.append(session_id)
        return [{"kind": "run_marker", "payload": {"status": "completed"}}]

    def idle(*, server_url: str, token: str, agent_id: str, session_id: str) -> None:
        return None

    monkeypatch.setattr(brave, "_create_profile_session", create)
    monkeypatch.setattr(brave, "_submit", submit)
    monkeypatch.setattr(brave, "_tool_events", events)
    monkeypatch.setattr(brave, "_wait_for_idle", idle)
    with pytest.raises(requests.HTTPError) as caught:
        brave._completed_success_sessions(
            server_url="server", token="token", agent_id="agent"
        )
    assert caught.value is rejection
    assert len(created) == 3
    # Snapshot 404 and server failure can follow admission and must still drain.
    assert drained == list(reversed(created if status in {404, 500} else created[:2]))
