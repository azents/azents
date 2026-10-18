"""Joint Routine judgment validates exact candidate membership and action shape."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.routine import ManualRoutineSource, RoutineContent
from azents.core.routine_judgment import (
    RoutineActionDecision,
    RoutineJudgmentCandidate,
    RoutineJudgmentDecision,
    RoutineSourceEvent,
    render_judgment_input,
)


def candidate(routine_id: str = "routine-a") -> RoutineJudgmentCandidate:
    """Return explicit eligible Manual context without previous execution."""
    return RoutineJudgmentCandidate(
        routine_id=routine_id,
        slug=f"slug-{routine_id}",
        content=RoutineContent(
            title="Traffic anomalies",
            objective=(
                "Check traffic an hour after the previous work; report anomalies."
            ),
            sources=(ManualRoutineSource(type="manual"),),
        ),
        events=(
            RoutineSourceEvent(
                source_type="manual",
                observed_at=datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC),
            ),
        ),
        last_executed_at=None,
        latest_work=None,
    )


def test_joint_action_and_no_action_are_independent_decisions() -> None:
    candidates = (candidate("a"), candidate("b"))
    decision = RoutineJudgmentDecision(
        decisions=(
            RoutineActionDecision(routine_id="a", act=False),
            RoutineActionDecision(routine_id="b", act=True),
        )
    )
    assert decision.validate_candidates(candidates) is decision
    assert [item.routine_id for item in decision.decisions if item.act] == ["b"]


@pytest.mark.parametrize("identities", [("a",), ("a", "foreign"), ()])
def test_omitted_or_foreign_output_is_failure_not_implicit_no_action(
    identities: tuple[str, ...],
) -> None:
    decision = RoutineJudgmentDecision(
        decisions=tuple(
            RoutineActionDecision(routine_id=value, act=False) for value in identities
        )
    )
    with pytest.raises(ValueError, match="every supplied candidate only"):
        decision.validate_candidates((candidate("a"), candidate("b")))


def test_duplicate_decisions_cannot_admit_two_occurrences() -> None:
    with pytest.raises(ValidationError, match="duplicate candidate identities"):
        RoutineJudgmentDecision(
            decisions=(
                RoutineActionDecision(routine_id="a", act=True),
                RoutineActionDecision(routine_id="a", act=False),
            )
        )


def test_invalid_text_or_new_objective_is_not_a_structured_decision() -> None:
    with pytest.raises(ValidationError):
        RoutineJudgmentDecision.model_validate_json("No action needed.")
    with pytest.raises(ValidationError):
        RoutineActionDecision.model_validate(
            {"routine_id": "a", "act": True, "objective": "Do something else."}
        )


def test_empty_or_duplicate_input_does_not_invoke_judgment() -> None:
    with pytest.raises(ValueError, match="do not require a model call"):
        render_judgment_input(())
    with pytest.raises(ValueError, match="duplicate candidates"):
        render_judgment_input((candidate(), candidate()))


@pytest.mark.parametrize("value", ["true", "false", 0, 1, None])
def test_action_requires_a_strict_boolean(value: object) -> None:
    with pytest.raises(ValidationError):
        RoutineActionDecision.model_validate({"routine_id": "a", "act": value})


def test_request_renders_candidate_context_not_flattened_conversation() -> None:
    rendered = render_judgment_input((candidate(),))
    assert '"last_executed_at":null' in rendered
    assert '"latest_work":null' in rendered
    assert '"type":"manual"' in rendered
    assert "an hour after the previous work" in rendered
    assert "Do not create a new objective" in rendered


def test_no_source_event_is_not_an_eligible_candidate() -> None:
    values = candidate().model_dump()
    values["events"] = ()
    with pytest.raises(ValidationError, match="must have source input"):
        RoutineJudgmentCandidate.model_validate(values)


def test_source_time_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        RoutineSourceEvent(
            source_type="manual", observed_at=datetime.datetime(2026, 10, 18)
        )
