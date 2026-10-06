"""Exact scope and minimal common execution binding contract tests."""

import dataclasses

import pytest
from pydantic import ValidationError

from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
    MemoryAcceptedOutcome,
    MemoryExecutionBinding,
    MemoryExecutionPrincipal,
    TakeoverMemoryAdmission,
)

_AGENT = "a" * 32
_WORKSPACE = "b" * 32
_USER = "c" * 32


@pytest.mark.parametrize(
    ("scope", "user"),
    [(ConsolidationScope.TEAM, None), (ConsolidationScope.USER, _USER)],
)
def test_unit_has_exactly_one_valid_corpus_owner(
    scope: ConsolidationScope, user: str | None
) -> None:
    unit = ConsolidationUnitKey(
        agent_id=_AGENT,
        workspace_id=_WORKSPACE,
        scope=scope,
        associated_user_id=user,
    )
    assert unit.scope is scope
    assert unit.associated_user_id == user


@pytest.mark.parametrize(
    ("scope", "user"),
    [(ConsolidationScope.TEAM, _USER), (ConsolidationScope.USER, None)],
)
def test_invalid_scope_owner_cannot_widen_input_authority(
    scope: ConsolidationScope, user: str | None
) -> None:
    with pytest.raises(ValidationError):
        ConsolidationUnitKey(
            agent_id=_AGENT,
            workspace_id=_WORKSPACE,
            scope=scope,
            associated_user_id=user,
        )


def test_binding_owns_only_domain_identity_budget_and_safe_accepted_outcome() -> None:
    assert {field.name for field in dataclasses.fields(MemoryExecutionBinding)} == {
        "unit_id",
        "unit",
        "session_id",
        "deadline_at",
        "execution_policy",
        "started_turns",
        "accepted",
    }
    assert {field.name for field in dataclasses.fields(MemoryExecutionPrincipal)} == {
        "binding",
        "owner",
        "run_id",
    }
    assert {field.name for field in dataclasses.fields(MemoryAcceptedOutcome)} == {
        "session_id",
        "tool_call_id",
        "accepted_at",
        "rendered_bytes",
        "settled_work_count",
    }


def test_takeover_caller_cannot_supply_a_fresh_deadline_or_turn_budget() -> None:
    assert {field.name for field in dataclasses.fields(TakeoverMemoryAdmission)} == {
        "predecessor_session_id",
        "expected_owner_generation",
    }
