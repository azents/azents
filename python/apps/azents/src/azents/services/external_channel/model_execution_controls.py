"""Control-local selection for registry-defined execution option groups."""

from collections.abc import Collection
from dataclasses import dataclass

from azents.core.model_execution_options import (
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
)

_NORMAL_PREFIX = "__normal__:"


@dataclass(frozen=True)
class ExecutionControlSelection:
    """Canonical selected IDs and an optional control-local group clear."""

    enabled: list[ModelExecutionOptionId]
    cleared_group: str | None


def normal_execution_value(group: str) -> str:
    """Represent the off choice without inventing a persisted option ID."""
    return f"{_NORMAL_PREFIX}{group}"


def execution_control_groups(
    definitions: Collection[ModelExecutionOptionDefinition],
) -> dict[str | None, list[ModelExecutionOptionDefinition]]:
    """Group controls solely by public registry metadata."""
    groups: dict[str | None, list[ModelExecutionOptionDefinition]] = {}
    for definition in definitions:
        groups.setdefault(definition.exclusive_group, []).append(definition)
    return groups


def decode_execution_control(values: Collection[str]) -> ExecutionControlSelection:
    """Reject conflicting off values before decoding provider option IDs."""
    normal = [value for value in values if value.startswith(_NORMAL_PREFIX)]
    if normal:
        group = normal[0].removeprefix(_NORMAL_PREFIX)
        if len(values) != 1 or not group:
            raise ValueError("Execution option selection is invalid.")
        return ExecutionControlSelection(enabled=[], cleared_group=group)
    return ExecutionControlSelection(
        enabled=[ModelExecutionOptionId(value) for value in values],
        cleared_group=None,
    )


def update_execution_control(
    *,
    definitions: Collection[ModelExecutionOptionDefinition],
    current: Collection[ModelExecutionOptionId],
    selected: Collection[ModelExecutionOptionId],
    cleared_group: str | None,
) -> list[ModelExecutionOptionId]:
    """Replace only the addressed control while retaining unrelated options.

    Registry/profile validation still owns whether the complete preference is
    valid. This boundary rejects forged control shapes instead of discarding
    their conflicts while merging a single-control update.
    """
    by_id = {definition.id: definition for definition in definitions}
    if len(selected) != len(set(selected)) or set(selected) - by_id.keys():
        raise ValueError("Execution option selection is invalid.")
    if cleared_group is not None:
        if selected or not any(
            definition.exclusive_group == cleared_group for definition in definitions
        ):
            raise ValueError("Execution option group is invalid.")
        group = cleared_group
    else:
        groups = {by_id[option].exclusive_group for option in selected}
        if len(groups) > 1:
            raise ValueError("Execution option selection spans multiple controls.")
        group = next(iter(groups)) if groups else None
        if group is not None and len(selected) != 1:
            raise ValueError("Execution option group requires one choice.")
        if group is None and not any(
            definition.exclusive_group is None for definition in definitions
        ):
            raise ValueError("Execution option selection is missing.")
    replaced = {
        definition.id
        for definition in definitions
        if definition.exclusive_group == group
    }
    return sorted(
        [option for option in current if option not in replaced] + list(selected),
        key=lambda option: option.value,
    )
