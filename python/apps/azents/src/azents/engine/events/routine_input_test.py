"""Ordinary Routine input is semantic history, unlike passive judgment output."""

import datetime

import pytest
from pydantic_ai.messages import ModelMessagesTypeAdapter

from azents.core.enums import EventKind, LLMProvider
from azents.core.routine_execution import RoutineExecutionRef
from azents.engine.events.filters import (
    _model_visible_event_text,
    _model_visible_event_value,
)
from azents.engine.events.routine_judgment_test import _pydantic, _responses
from azents.engine.events.types import (
    Event,
    RoutineInputPayload,
    RoutineNotificationPayload,
)


@pytest.mark.parametrize(
    "kind", [EventKind.ROUTINE_TRIGGER, EventKind.ROUTINE_CONTINUATION]
)
def test_routine_input_preserves_semantic_context_in_both_lowerers(
    kind: EventKind,
) -> None:
    content = "Execute the original admitted objective and preserve other Session work."
    event = Event(
        id="1" * 32,
        session_id="routine-input-session",
        kind=kind,
        payload=RoutineInputPayload(
            executions=(
                RoutineExecutionRef(
                    routine_id="routine-a",
                    execution_id="occurrence-a",
                    slug="routine-a",
                    title="Original title",
                ),
            ),
            content=content,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    pydantic_request = _pydantic(LLMProvider.OPENROUTER, structured=False).lower(
        [event],
        model="exact-selected-model",
        native_replay_context=None,
    )
    responses = _responses(structured=False).lower(
        [event],
        model="exact-selected-model",
        native_replay_context=None,
    )
    assert (
        content
        in ModelMessagesTypeAdapter.dump_json(pydantic_request.messages).decode()
    )
    assert {"role": "user", "content": content} in responses.input
    assert _model_visible_event_value(event) == {"role": "user", "content": content}
    continuity = _model_visible_event_text(event, include_label=True)
    assert continuity is not None and content in continuity


def test_routine_chat_notification_is_assistant_history_in_both_lowerers() -> None:
    """No native provider artifact or ordinary turn usage is invented."""
    content = "A verified change needs your attention."
    event = Event(
        id="2" * 32,
        session_id="routine-notification-session",
        kind=EventKind.ROUTINE_NOTIFICATION,
        payload=RoutineNotificationPayload(
            execution_id="occurrence-a",
            slug="routine-a",
            title="Routine A",
            content=content,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    lowered = _pydantic(LLMProvider.OPENROUTER, structured=False).lower(
        [event], model="exact-selected-model", native_replay_context=None
    )
    assert content in ModelMessagesTypeAdapter.dump_json(lowered.messages).decode()
    responses = _responses(structured=False).lower(
        [event], model="exact-selected-model", native_replay_context=None
    )
    assert {"role": "assistant", "content": content} in responses.input
    assert _model_visible_event_value(event) == {
        "role": "assistant",
        "content": content,
    }
    assert content in (_model_visible_event_text(event, include_label=True) or "")
