"""Content-free PostgreSQL preflight for External Channel cutover."""

import dataclasses
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository


class _ExternalChannelCutoverPreflightCounts(Protocol):
    """Repository-owned aggregate count projection."""

    @property
    def undrained_events(self) -> int: ...

    @property
    def unactivated_bindings(self) -> int: ...

    @property
    def incomplete_hydrations(self) -> int: ...

    @property
    def pending_contexts(self) -> int: ...

    @property
    def open_conversation_admissions(self) -> int: ...

    @property
    def pending_access_requests(self) -> int: ...

    @property
    def inflight_resource_provisionings(self) -> int: ...

    @property
    def active_bindings_without_delivery_target(self) -> int: ...

    @property
    def active_bindings_without_session(self) -> int: ...

    @property
    def active_bindings_without_route(self) -> int: ...

    @property
    def active_bindings_without_latest_batch(self) -> int: ...

    @property
    def active_bindings_without_thread_position(self) -> int: ...

    @property
    def active_bindings_with_ambiguous_thread_position(self) -> int: ...


class _ExternalChannelCutoverPreflightRepository(Protocol):
    """Persistence boundary required by the preflight service."""

    async def get_cutover_preflight_counts(
        self,
        session: AsyncSession,
    ) -> _ExternalChannelCutoverPreflightCounts:
        """Return aggregate-only cutover safety counts."""
        ...


type _SessionManager = SessionManager[AsyncSession]
type _SessionContext = AbstractAsyncContextManager[AsyncSession]


@dataclasses.dataclass(frozen=True)
class ExternalChannelCutoverPreflightReport:
    """Stable content-free cutover gate result."""

    category_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        """Reject negative or duplicate category counts."""
        category_names = tuple(name for name, _count in self.category_counts)
        if len(category_names) != len(set(category_names)):
            raise ValueError("External Channel preflight categories must be unique.")
        if any(count < 0 for _name, count in self.category_counts):
            raise ValueError("External Channel preflight counts must not be negative.")

    @property
    def ready(self) -> bool:
        """Return whether every cutover invariant is satisfied."""
        return all(count == 0 for _name, count in self.category_counts)


@dataclasses.dataclass
class ExternalChannelCutoverPreflightService:
    """Evaluate the guarded External Channel cutover without mutation."""

    repository: Annotated[
        _ExternalChannelCutoverPreflightRepository,
        Depends(ExternalChannelRepository),
    ]
    session_manager: Annotated[
        _SessionManager,
        Depends(get_session_manager),
    ]

    async def preflight(self) -> ExternalChannelCutoverPreflightReport:
        """Return aggregate invariant counts from one read-only transaction."""
        async with self.session_manager() as session:
            counts = await self.repository.get_cutover_preflight_counts(session)
        return build_external_channel_cutover_preflight_report(counts)


def build_external_channel_cutover_preflight_report(
    counts: _ExternalChannelCutoverPreflightCounts,
) -> ExternalChannelCutoverPreflightReport:
    """Map repository count names to stable operator categories."""
    return ExternalChannelCutoverPreflightReport(
        category_counts=(
            ("legacy_events_not_drained", counts.undrained_events),
            ("bindings_not_active", counts.unactivated_bindings),
            ("hydrations_not_complete", counts.incomplete_hydrations),
            ("pending_context_present", counts.pending_contexts),
            ("conversation_admissions_open", counts.open_conversation_admissions),
            ("access_requests_pending", counts.pending_access_requests),
            (
                "resource_provisioning_inflight",
                counts.inflight_resource_provisionings,
            ),
            (
                "active_binding_delivery_target_missing",
                counts.active_bindings_without_delivery_target,
            ),
            (
                "active_binding_session_missing",
                counts.active_bindings_without_session,
            ),
            (
                "active_binding_route_missing",
                counts.active_bindings_without_route,
            ),
            (
                "active_binding_latest_batch_missing",
                counts.active_bindings_without_latest_batch,
            ),
            (
                "active_binding_thread_position_missing",
                counts.active_bindings_without_thread_position,
            ),
            (
                "active_binding_thread_position_ambiguous",
                counts.active_bindings_with_ambiguous_thread_position,
            ),
        )
    )
