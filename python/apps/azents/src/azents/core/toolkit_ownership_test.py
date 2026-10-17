"""Closed canonical ownership parsing and saved policy predicates."""

import pytest
from pydantic import ValidationError

from azents.core.toolkit_ownership import (
    PersonalToolkitAccess,
    PersonalToolkitAccessMode,
    ToolkitOwnerKind,
    toolkit_owner_adapter,
)


@pytest.mark.parametrize(
    "payload,kind",
    [
        ({"kind": "workspace", "workspace_id": "w"}, ToolkitOwnerKind.WORKSPACE),
        (
            {"kind": "agent", "workspace_id": "w", "agent_id": "a"},
            ToolkitOwnerKind.AGENT,
        ),
        ({"kind": "user", "user_id": "u", "workspace_id": "w"}, ToolkitOwnerKind.USER),
    ],
)
def test_explicit_legal_owner_variants(
    payload: dict[str, str], kind: ToolkitOwnerKind
) -> None:
    """Each owner is explicit and preserves its exact canonical keys."""
    owner = toolkit_owner_adapter.validate_python(payload)
    assert owner.kind is kind
    assert owner.model_dump(mode="json") == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "user", "user_id": "u"},
        {"kind": "user", "user_id": "u", "workspace_id": "w", "agent_id": "a"},
        {"kind": "workspace", "workspace_id": "w", "user_id": "u"},
        {"kind": "agent", "agent_id": "a"},
        {"workspace_id": "w"},
        {"kind": "unknown", "user_id": "u"},
    ],
)
def test_reject_ambiguous_owner_payloads(payload: dict[str, str]) -> None:
    """Missing or conflicting ownership is not guessed or defaulted."""
    with pytest.raises(ValidationError):
        toolkit_owner_adapter.validate_python(payload)


def test_policy_only_predicate_does_not_pretend_to_check_ordinary_access() -> None:
    """All and Selected represent saved permission, not current User admission."""
    all_access = PersonalToolkitAccess("t", "u", "w", PersonalToolkitAccessMode.ALL, ())
    selected = PersonalToolkitAccess(
        "t", "u", "w", PersonalToolkitAccessMode.SELECTED, ("a",)
    )
    assert all_access.allows_agent("future")
    assert selected.allows_agent("a")
    assert not selected.allows_agent("future")
