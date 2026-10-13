"""Runtime environment desired-list and secret-safe validation tests."""

import pytest
from pydantic import SecretStr

from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    ReplacementRuntimeEnvironmentValue,
    RuntimeEnvironmentEntryEdit,
    StoredRuntimeEnvironmentValue,
    merge_runtime_environment,
    parse_runtime_environment,
    validate_runtime_environment,
)


def _replace(name: str, value: str) -> RuntimeEnvironmentEntryEdit:
    return RuntimeEnvironmentEntryEdit(
        name=name,
        value=ReplacementRuntimeEnvironmentValue(
            type="replace", value=SecretStr(value)
        ),
    )


def _keep(name: str, stored_name: str) -> RuntimeEnvironmentEntryEdit:
    return RuntimeEnvironmentEntryEdit(
        name=name, value=StoredRuntimeEnvironmentValue(type="stored", name=stored_name)
    )


def test_retention_rename_replace_and_delete() -> None:
    assert merge_runtime_environment(
        {"KEEP": "old-secret", "REMOVE": "removed", "REPLACE": "old"},
        [
            _keep("RENAMED", "KEEP"),
            _replace("REPLACE", "new-secret"),
            _replace("EMPTY", ""),
        ],
    ) == {"RENAMED": "old-secret", "REPLACE": "new-secret", "EMPTY": ""}
    assert merge_runtime_environment({"A": "old"}, []) == {}


@pytest.mark.parametrize(
    "values",
    [
        {"BAD=NAME": "sensitive"},
        {"A" * 65: "sensitive"},
        {"A": "sensitive\0"},
        {"A": "sensitive\ud800"},
        {"A": "한" * 1366},
        {f"V{i}": "v" for i in range(51)},
        {f"V{i}": "sensitive" + "v" * 3990 for i in range(30)},
    ],
)
def test_limits_are_validated_without_secret_values(values: dict[str, str]) -> None:
    with pytest.raises(InvalidRuntimeEnvironment) as error:
        validate_runtime_environment(values)
    assert "sensitive" not in str(error.value)
    assert "한" not in str(error.value)


@pytest.mark.parametrize(
    "edits",
    [
        [_replace("A", "secret-a"), _replace("A", "secret-b")],
        [_keep("A", "MISSING")],
        [_keep("A", "SOURCE"), _keep("B", "SOURCE")],
    ],
)
def test_duplicate_names_and_invalid_stored_references(
    edits: list[RuntimeEnvironmentEntryEdit],
) -> None:
    with pytest.raises(InvalidRuntimeEnvironment):
        merge_runtime_environment({"SOURCE": "secret"}, edits)


def test_valid_posix_names_empty_values_and_utf8_boundary() -> None:
    validate_runtime_environment(
        {"_token": "", "lowerCase2": "a\nb", "UNICODE": "한" * 1365}
    )
    assert parse_runtime_environment('{"A":"secret"}') == {"A": "secret"}


def test_invalid_persisted_body_is_safe_and_replacement_repr_is_redacted() -> None:
    with pytest.raises(InvalidRuntimeEnvironment) as error:
        parse_runtime_environment('{"A":{"value":"hidden-secret"}}')
    assert "hidden-secret" not in str(error.value)
    assert "hidden-secret" not in repr(_replace("A", "hidden-secret"))
