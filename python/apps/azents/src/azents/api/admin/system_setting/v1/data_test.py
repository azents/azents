"""Presence-aware Admin patch schema regressions."""

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.core.system_setting import SystemSettingSecretActionType

from .data import (
    ExternalAccountOAuthPatchRequest,
    ExternalChannelFilesPatchRequest,
    PlatformGitHubAppPatchRequest,
    SystemSettingSecretActionRequest,
)

_GITHUB_PATCH = TypeAdapter(PlatformGitHubAppPatchRequest)
_OAUTH_PATCH = TypeAdapter(ExternalAccountOAuthPatchRequest)
_FILES_PATCH = TypeAdapter(ExternalChannelFilesPatchRequest)


def test_github_patch_preserves_omission_and_explicit_null() -> None:
    """Only supplied fields reach the mutation; null retains its own meaning."""
    omitted = _GITHUB_PATCH.validate_python({"expected_version": "3"})
    cleared = _GITHUB_PATCH.validate_python({"expected_version": 3, "client_id": None})

    assert omitted == {"expected_version": 3}
    assert cleared == {"expected_version": 3, "client_id": None}
    assert "client_id" not in omitted


def test_oauth_patch_preserves_omission_and_explicit_null() -> None:
    """OAuth optional non-secret fields do not gain defaults after decoding."""
    omitted = _OAUTH_PATCH.validate_python({"expected_version": 2})
    cleared = _OAUTH_PATCH.validate_python(
        {"expected_version": 2, "application_id": None}
    )

    assert omitted == {"expected_version": 2}
    assert cleared == {"expected_version": 2, "application_id": None}


def test_file_patch_preserves_explicit_null_for_route_validation() -> None:
    """An explicit null limit is distinguishable from an omitted limit."""
    omitted = _FILES_PATCH.validate_python({"expected_version": 1})
    invalid_limit = _FILES_PATCH.validate_python(
        {"expected_version": 1, "outbound_max_file_bytes": None}
    )

    assert omitted == {"expected_version": 1}
    assert invalid_limit == {
        "expected_version": 1,
        "outbound_max_file_bytes": None,
    }


@pytest.mark.parametrize("expected_version", [-1, None])
def test_all_patches_reject_invalid_required_version(
    expected_version: int | None,
) -> None:
    """Each patch keeps the original nonnegative required version constraint."""
    payload = {"expected_version": expected_version}
    with pytest.raises(ValidationError):
        _GITHUB_PATCH.validate_python(payload)
    with pytest.raises(ValidationError):
        _OAUTH_PATCH.validate_python(payload)
    with pytest.raises(ValidationError):
        _FILES_PATCH.validate_python(payload)


def test_all_patches_require_version() -> None:
    """Optional selection never makes the optimistic version optional."""
    with pytest.raises(ValidationError):
        _GITHUB_PATCH.validate_python({})
    with pytest.raises(ValidationError):
        _OAUTH_PATCH.validate_python({})
    with pytest.raises(ValidationError):
        _FILES_PATCH.validate_python({})


def test_patch_schemas_keep_required_keys_and_published_null_defaults() -> None:
    """Documentation defaults do not materialize omitted runtime patch keys."""
    for adapter in (_GITHUB_PATCH, _OAUTH_PATCH, _FILES_PATCH):
        schema = adapter.json_schema()
        assert schema["required"] == ["expected_version"]
        for name, field in schema["properties"].items():
            if name != "expected_version":
                assert field["default"] is None
        assert adapter.validate_python({"expected_version": 0}) == {
            "expected_version": 0
        }


def test_unknown_field_behavior_matches_existing_contracts() -> None:
    """File limits reject unknown keys; GitHub and OAuth retain ignore semantics."""
    payload = {"expected_version": 0, "future_field": "ignored"}

    assert _GITHUB_PATCH.validate_python(payload) == {"expected_version": 0}
    assert _OAUTH_PATCH.validate_python(payload) == {"expected_version": 0}
    with pytest.raises(ValidationError):
        _FILES_PATCH.validate_python(payload)


@pytest.mark.parametrize("value", [0, 100 * 1024 * 1024 + 1])
def test_file_limits_keep_ingress_bounds(value: int) -> None:
    """A TypedDict decoder preserves the published configured file bounds."""
    with pytest.raises(ValidationError):
        _FILES_PATCH.validate_python(
            {"expected_version": 0, "outbound_max_file_bytes": value}
        )


def test_secret_value_object_is_validated_without_inserting_omitted_keys() -> None:
    """Nested secret actions retain runtime validation and typed fields."""
    payload = _GITHUB_PATCH.validate_python(
        {
            "expected_version": 0,
            "private_key": {"action": "replace", "value": "replacement"},
        }
    )
    action = payload["private_key"]
    assert isinstance(action, SystemSettingSecretActionRequest)
    assert action.action is SystemSettingSecretActionType.REPLACE
    assert action.value == "replacement"
    assert "client_secret" not in payload

    with pytest.raises(ValidationError):
        _GITHUB_PATCH.validate_python(
            {"expected_version": 0, "private_key": {"action": "replace"}}
        )
