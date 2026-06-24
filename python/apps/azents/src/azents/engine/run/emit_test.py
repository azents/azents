"""Emit helper tests."""

import datetime

from azents.core.enums import EventKind
from azents.engine.events.types import (
    AssistantMessagePayload,
    AttachmentOutputPart,
    Event,
    NativeArtifact,
    OutputTextPart,
    build_native_compat_key,
)
from azents.engine.run.emit import collect_event_result


def _native_artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    compat_key = build_native_compat_key(
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
    )
    return NativeArtifact(
        compat_key=compat_key,
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "message"},
    )


def test_collect_event_result_reads_event_assistant_output() -> None:
    """Collect Event assistant output as subagent return value."""
    event = Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content=[
                OutputTextPart(text="final answer"),
                AttachmentOutputPart(
                    uri="exchange://exchange/workspace/files/object/original",
                    name="report.txt",
                    media_type="text/plain",
                    size=12,
                    preview_summary="summary",
                ),
            ],
            native_artifact=_native_artifact(),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    texts: list[str] = []
    attachments = []

    collect_event_result(event, texts, attachments)

    assert texts == ["final answer"]
    assert len(attachments) == 1
    assert attachments[0].uri == "exchange://exchange/workspace/files/object/original"
    assert attachments[0].name == "report.txt"
    assert attachments[0].text_preview == "summary"
