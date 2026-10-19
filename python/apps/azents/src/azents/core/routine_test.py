"""Routine contracts preserve content and separate recording from notification."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.routine import (
    MAX_ROUTINE_WORK_RECORDS,
    MAX_ROUTINES_PER_SESSION,
    ROUTINE_MIN_ACTION_DELAY,
    ROUTINE_TICK_INTERVAL,
    ManualRoutineSource,
    RoutineChanges,
    RoutineContent,
    RoutineContentConflict,
    RoutineObjectiveOutcome,
    RoutineWorkResult,
    update_routine_content,
)


def _content() -> RoutineContent:
    """Return exact content, including deliberately significant whitespace."""
    return RoutineContent(
        title=" Product news ",
        objective="Watch official release news.\nKeep launch rumors distinct.",
        sources=(ManualRoutineSource(type="manual"),),
    )


def test_initial_limits_and_distinct_timing_concepts() -> None:
    assert MAX_ROUTINES_PER_SESSION == 20
    assert MAX_ROUTINE_WORK_RECORDS == 100
    assert ROUTINE_TICK_INTERVAL == datetime.timedelta(minutes=30)
    assert ROUTINE_MIN_ACTION_DELAY == datetime.timedelta(minutes=30)


def test_exact_update_preserves_unrelated_content() -> None:
    original = _content()
    updated = update_routine_content(
        current=original,
        expected=RoutineContent.model_validate(original.model_dump(mode="json")),
        changes={"title": "Launch news"},
    )
    assert updated.title == "Launch news"
    assert updated.objective == original.objective
    assert updated.sources == original.sources
    assert original.title == " Product news "


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "Product news"},
        {"objective": "Watch official release news."},
        {"sources": ()},
    ],
)
def test_incomplete_or_normalized_prior_content_cannot_overwrite(
    changes: RoutineChanges,
) -> None:
    current = _content()
    wrong_prior = RoutineContent.model_validate({**current.model_dump(), **changes})
    with pytest.raises(RoutineContentConflict, match="Read the current content"):
        update_routine_content(
            current=current,
            expected=wrong_prior,
            changes={"objective": "Check traffic anomalies."},
        )
    assert current == _content()


def test_missing_prior_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RoutineContent.model_validate({"objective": "Only this part was read."})


def test_empty_change_set_is_a_content_preserving_noop() -> None:
    current = _content()
    assert (
        update_routine_content(current=current, expected=current, changes={}) == current
    )


def test_source_changes_are_explicit_and_empty_source_set_is_representable() -> None:
    current = _content()
    updated = update_routine_content(
        current=current, expected=current, changes={"sources": ()}
    )
    assert updated.sources == ()
    assert updated.title == current.title
    assert updated.objective == current.objective


@pytest.mark.parametrize("source_type", ["email", "webhook", "script"])
def test_unimplemented_source_operations_are_not_accepted(source_type: str) -> None:
    with pytest.raises(ValidationError):
        ManualRoutineSource.model_validate({"type": source_type})


def test_manual_source_has_no_user_click_or_unimplemented_options() -> None:
    assert ManualRoutineSource(type="manual").model_dump() == {"type": "manual"}
    with pytest.raises(ValidationError):
        ManualRoutineSource.model_validate({"type": "manual", "webhook_url": "x"})


@pytest.mark.parametrize("field", ["title", "objective"])
def test_blank_content_rejected_without_normalizing_valid_content(field: str) -> None:
    values = _content().model_dump()
    values[field] = " \n "
    with pytest.raises(ValidationError, match="must not be blank"):
        RoutineContent.model_validate(values)


@pytest.mark.parametrize("outcome", list(RoutineObjectiveOutcome))
def test_silent_result_records_honest_objective_outcome(
    outcome: RoutineObjectiveOutcome,
) -> None:
    work = RoutineWorkResult(
        objective_outcome=outcome,
        result="No confirmed announcement was found.",
        next_hint="Check official announcements at the next eligible opportunity.",
        notify=False,
        message=None,
    )
    assert work.objective_outcome is outcome
    assert work.result
    assert work.next_hint
    assert work.message is None


@pytest.mark.parametrize("message", ["Do not send this.", ""])
def test_silent_result_forbids_even_empty_user_message(message: str) -> None:
    with pytest.raises(ValidationError, match="must not include a message"):
        RoutineWorkResult(
            objective_outcome=RoutineObjectiveOutcome.FINISHED,
            result="Checked the announcement.",
            next_hint="Wait for a new official statement.",
            notify=False,
            message=message,
        )


@pytest.mark.parametrize("message", [None, "", " \n "])
def test_notifying_result_requires_nonblank_user_message(message: str | None) -> None:
    with pytest.raises(ValidationError, match="requires a user message"):
        RoutineWorkResult(
            objective_outcome=RoutineObjectiveOutcome.FINISHED,
            result="An official release date was announced.",
            next_hint="Check for changes to the announced date.",
            notify=True,
            message=message,
        )


def test_notifying_result_preserves_markdown_message() -> None:
    message = "**Official announcement**\nThe release date is confirmed."
    work = RoutineWorkResult(
        objective_outcome=RoutineObjectiveOutcome.FINISHED,
        result="The official release date is confirmed.",
        next_hint="Watch for a change to that date.",
        notify=True,
        message=message,
    )
    assert work.message == message


def test_result_guidance_does_not_add_sentence_or_character_validation() -> None:
    text = "A retained contextual detail. " * 2000
    work = RoutineWorkResult(
        objective_outcome=RoutineObjectiveOutcome.FAILED,
        result=text,
        next_hint="Two sentences are allowed. Brevity remains prompt guidance.",
        notify=False,
        message=None,
    )
    assert work.result == text
