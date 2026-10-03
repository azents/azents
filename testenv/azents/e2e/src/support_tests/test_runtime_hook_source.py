"""Pure contracts for the actual bounded runtime-hook source wait helper."""

import json

import pytest
from testcontainers.core.container import DockerContainer

from tests.required.public import test_agent_execution_persistence as persistence


class _HookLogContainer(DockerContainer):
    """Supply captured log bytes without initializing Docker or a listener."""

    def __init__(self, frames: tuple[tuple[bytes, bytes], ...]) -> None:
        self.frames = frames
        self.reads = 0

    def get_logs(self) -> tuple[bytes, bytes]:
        frame = self.frames[min(self.reads, len(self.frames) - 1)]
        self.reads += 1
        return frame


class _HookObservationClock:
    """Advance only when the bounded authoritative polling requests a wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.waits = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.now += duration
        self.waits += 1


def _hook_source_record() -> dict[str, object]:
    return {
        "message": "Runtime hook QA lifecycle event",
        "runtime_hook_qa_lifecycle": "on_before_tool_call",
        "tool_name": "dupmcp__instance",
        "toolkit_slug": "dupmcp",
        "session_id": "session",
        "future_log_field": {"retained": True},
    }


def _install_hook_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> _HookObservationClock:
    clock = _HookObservationClock()
    monkeypatch.setattr(persistence.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(persistence.time, "sleep", clock.sleep)
    return clock


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize(
    ("tool_name", "namespace"),
    [("dupmcp__instance", "dupmcp"), ("dupmcp_2__instance", "dupmcp_2")],
)
def test_runtime_hook_source_accepts_structured_lifecycle(
    monkeypatch: pytest.MonkeyPatch, stream: str, tool_name: str, namespace: str
) -> None:
    clock = _install_hook_clock(monkeypatch)
    record = _hook_source_record()
    record["tool_name"] = tool_name
    record["toolkit_slug"] = namespace
    log = b"not-json\n[]\n" + json.dumps(record).encode()
    frame = (log, b"") if stream == "stdout" else (b"", log)
    container = _HookLogContainer((frame,))

    persistence._wait_for_runtime_hook_source(
        container,
        tool_name=tool_name,
        toolkit_namespace=namespace,
        timeout=1,
    )

    assert container.reads == 1
    assert clock.waits == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("message", "Runtime hook QA lifecycle event: on_before_tool_call"),
        ("message", "Unrelated event"),
        ("runtime_hook_qa_lifecycle", None),
        ("runtime_hook_qa_lifecycle", "on_after_tool_call"),
        ("tool_name", "dupmcp_2__instance"),
        ("toolkit_slug", "dupmcp_2"),
    ],
)
def test_runtime_hook_source_rejects_wrong_evidence(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    clock = _install_hook_clock(monkeypatch)
    record = _hook_source_record()
    record[field] = value
    container = _HookLogContainer(((json.dumps(record).encode(), b""),))

    with pytest.raises(
        TimeoutError, match="Runtime hook did not observe Toolkit source"
    ):
        persistence._wait_for_runtime_hook_source(
            container,
            tool_name="dupmcp__instance",
            toolkit_namespace="dupmcp",
            timeout=0.2,
        )

    assert container.reads == 2
    assert clock.waits == 2


def test_runtime_hook_source_rejects_missing_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_hook_clock(monkeypatch)
    record = _hook_source_record()
    del record["runtime_hook_qa_lifecycle"]
    container = _HookLogContainer(((json.dumps(record).encode(), b""),))

    with pytest.raises(
        TimeoutError, match="Runtime hook did not observe Toolkit source"
    ):
        persistence._wait_for_runtime_hook_source(
            container,
            tool_name="dupmcp__instance",
            toolkit_namespace="dupmcp",
            timeout=0.2,
        )

    assert container.reads == clock.waits == 2


def test_runtime_hook_source_waits_for_matching_authoritative_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _install_hook_clock(monkeypatch)
    wrong = _hook_source_record()
    wrong["toolkit_slug"] = "dupmcp_2"
    container = _HookLogContainer(
        (
            (json.dumps(wrong).encode(), b""),
            (json.dumps(_hook_source_record()).encode(), b""),
        )
    )

    persistence._wait_for_runtime_hook_source(
        container,
        tool_name="dupmcp__instance",
        toolkit_namespace="dupmcp",
        timeout=1,
    )

    assert container.reads == 2
    assert clock.waits == 1
