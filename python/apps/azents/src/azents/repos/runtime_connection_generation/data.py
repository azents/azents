"""Runtime connection-generation persistence data contracts."""

import datetime
from dataclasses import dataclass

from azents.core.enums import RuntimeConnectionAuthorityKind


@dataclass(frozen=True)
class RuntimeConnectionGenerationCutover:
    """Persisted allocator cutover marker."""

    allocator_version: int
    cutover_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeConnectionGeneration:
    """Persisted allocated and accepted generation state."""

    connection_kind: RuntimeConnectionAuthorityKind
    subject_id: str
    high_water_generation: int
    accepted_generation: int
    created_at: datetime.datetime
    updated_at: datetime.datetime


class RuntimeConnectionGenerationIntegrityError(RuntimeError):
    """Raised when durable generation authority is missing or inconsistent."""


class RuntimeConnectionGenerationExhausted(RuntimeError):
    """Raised when allocating another signed BIGINT generation is impossible."""
