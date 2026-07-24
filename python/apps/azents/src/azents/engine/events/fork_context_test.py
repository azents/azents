"""Fork context utility tests."""

import datetime

import pytest

from azents.core.enums import EventKind
from azents.engine.events.fork_context import (
    InvalidForkTurns,
    degrade_file_parts_for_fork,
    parse_fork_turns,
    select_fork_events,
)
from azents.engine.events.types import (
    Event,
    EventPayload,
    FileOutputPart,
    InputTextPart,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
)

_NOW = datetime.datetime.now(datetime.UTC)


def _event(
    id_suffix: str,
    kind: EventKind,
    payload: EventPayload,
    *,
    model_order: int,
) -> Event:
    return Event(
        id=f"{id_suffix:0>32}"[-32:],
        session_id="session-1",
        kind=kind,
        payload=payload,
        model_order=model_order,
        created_at=_NOW,
    )


def _user_event(id_suffix: str, text: str, *, model_order: int) -> Event:
    return _event(
        id_suffix,
        EventKind.USER_MESSAGE,
        UserMessagePayload(sender_user_id=None, content=text),
        model_order=model_order,
    )


def _turn_marker(id_suffix: str, *, model_order: int) -> Event:
    return _event(
        id_suffix,
        EventKind.TURN_MARKER,
        TurnMarkerPayload(
            run_id=f"run-{id_suffix}",
            usage=TokenUsagePayload(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                raw={},
            ),
        ),
        model_order=model_order,
    )


@pytest.mark.parametrize(
    ("raw", "mode", "count"),
    [
        ("none", "none", None),
        ("all", "all", None),
        ("1", "latest", 1),
        ("25", "latest", 25),
    ],
)
def test_parse_fork_turns_accepts_valid_values(
    raw: str,
    mode: str,
    count: int | None,
) -> None:
    """fork_turns accepts none, all, and positive integer strings."""
    parsed = parse_fork_turns(raw)

    assert parsed.mode == mode
    assert parsed.count == count


@pytest.mark.parametrize("raw", ["", "0", "-1", "+1", "1.5", "latest", "all "])
def test_parse_fork_turns_rejects_invalid_values(raw: str) -> None:
    """Malformed fork_turns values fail before child creation."""
    with pytest.raises(InvalidForkTurns):
        parse_fork_turns(raw)


def test_select_fork_events_none_returns_empty() -> None:
    """none starts with no parent transcript context."""
    events = [_user_event("1", "before", model_order=1000)]

    selected = select_fork_events(
        events,
        parse_fork_turns("none"),
        head_event_id=None,
    )

    assert selected == []


def test_select_fork_events_all_starts_at_head_boundary() -> None:
    """all copies only the current model-visible range from the head boundary."""
    before = _user_event("1", "before head", model_order=1000)
    head = _user_event("2", "summary/head", model_order=2000)
    after = _user_event("3", "after head", model_order=3000)

    selected = select_fork_events(
        [after, before, head],
        parse_fork_turns("all"),
        head_event_id=head.id,
    )

    assert [event.id for event in selected] == [head.id, after.id]


def test_select_fork_events_latest_turns_within_head_range() -> None:
    """Positive integer values select recent turns only inside the head range."""
    before_head = _user_event("1", "before head", model_order=1000)
    head = _user_event("2", "summary/head", model_order=2000)
    old_turn_user = _user_event("3", "old turn", model_order=3000)
    old_marker = _turn_marker("4", model_order=4000)
    latest_turn_user = _user_event("5", "latest turn", model_order=5000)
    latest_marker = _turn_marker("6", model_order=6000)

    selected = select_fork_events(
        [latest_marker, before_head, latest_turn_user, old_marker, head, old_turn_user],
        parse_fork_turns("1"),
        head_event_id=head.id,
    )

    assert [event.id for event in selected] == [latest_turn_user.id, latest_marker.id]


def test_degrade_file_parts_for_fork_replaces_user_file_with_placeholder() -> None:
    """FilePart bytes are not copied; metadata is rendered as text placeholder."""
    source = _event(
        "a",
        EventKind.USER_MESSAGE,
        UserMessagePayload(
            sender_user_id=None,
            content=[
                InputTextPart(text="Please inspect this."),
                FileOutputPart(
                    model_file_id="model-file-1",
                    media_type="application/pdf",
                    name="brief.pdf",
                    size=123,
                    kind="document",
                ),
            ],
        ),
        model_order=1000,
    )

    [degraded] = degrade_file_parts_for_fork([source])

    assert isinstance(degraded.payload, UserMessagePayload)
    assert isinstance(degraded.payload.content, list)
    assert all(
        not isinstance(part, FileOutputPart) for part in degraded.payload.content
    )
    placeholder = degraded.payload.content[1]
    assert isinstance(placeholder, InputTextPart)
    assert "file bytes were not copied" in placeholder.text
    assert "brief.pdf" in placeholder.text
    assert "application/pdf" in placeholder.text
    assert "123 bytes" in placeholder.text
    assert "model-file-1" in placeholder.text
    assert source.id in placeholder.text
