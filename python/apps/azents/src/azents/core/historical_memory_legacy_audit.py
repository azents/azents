"""Truthful scalar diagnostics for retired Memory jobs, never execution authority."""

import enum


class MemoryLegacyRecordedOutcome(enum.StrEnum):
    """The prior job's recorded outcome at migration, including unfinished jobs."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class MemoryLegacyCostMethod(enum.StrEnum):
    """The normalized cost provenance already recorded by the retired job."""

    PROVIDER_REPORTED = "provider_reported"
    ESTIMATED = "estimated"
