"""Durable Multi App selector catalog and immutable route selection."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelSetupClaimStatus,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelCatalogRoute,
    ExternalChannelChannelDefaultCreate,
    ExternalChannelInteraction,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_state_from_interaction,
)

_SELECTOR_PAGE_SIZE = 20


class ExternalChannelSelectorError(ValueError):
    """A selector request does not match current durable routing state."""


@dataclass(frozen=True)
class ExternalChannelSelectorCandidate:
    """One current visible Agent candidate."""

    route_id: str
    agent_name: str
    access: Literal["available", "access_required"]


@dataclass(frozen=True)
class ExternalChannelSelectorCatalog:
    """A bounded deterministic page from the current Multi App catalog."""

    candidates: tuple[ExternalChannelSelectorCandidate, ...]
    next_offset: int | None


@dataclass(frozen=True)
class ExternalChannelSelectorSelection:
    """One immutable selection result or its existing binding winner."""

    status: Literal[
        "selected",
        "already_selected",
        "already_bound",
        "setup_pending_location",
        "expired",
    ]
    selector_interaction: ExternalChannelInteraction
    binding: ExternalChannelBinding | None


@dataclass
class ExternalChannelSelectorService:
    """Project and select routes from interaction-owned selector state."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]

    async def project_catalog(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorCatalog:
        """Load one bounded catalog page from trusted selector state."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=selector_interaction_id,
            )
            state = _selector_state(
                interaction,
                principal_id=principal_id,
                now=now,
            )
            assert interaction is not None
            connection = await self.repository.get_connection(
                session,
                connection_id=state.connection_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
                or connection.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
            ):
                raise ExternalChannelSelectorError(
                    "Selector interaction is unavailable."
                )
            principal = await self.repository.get_principal(
                session,
                principal_id=principal_id,
            )
            if (
                principal is None
                or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
            ):
                raise ExternalChannelSelectorError("Selector principal is unavailable.")
            rows = await self.repository.list_routable_multi_catalog_routes(
                session,
                connection_id=connection.id,
                principal_id=principal_id,
                author_type=principal.author_type,
                search=search,
                offset=offset,
                limit=_SELECTOR_PAGE_SIZE + 1,
            )
            candidates = await self._visible_candidates(
                session,
                rows=rows[:_SELECTOR_PAGE_SIZE],
                principal_id=principal_id,
                setup_claim_id=interaction.setup_claim_id,
            )
            return ExternalChannelSelectorCatalog(
                candidates=tuple(candidates),
                next_offset=(
                    offset + _SELECTOR_PAGE_SIZE
                    if len(rows) > _SELECTOR_PAGE_SIZE
                    else None
                ),
            )

    async def select_route(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        route_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorSelection:
        """Apply one immutable trusted route choice."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=selector_interaction_id,
            )
            state = _selector_state(
                interaction,
                principal_id=principal_id,
                now=None,
            )
            assert interaction is not None
            if interaction.expires_at <= now:
                expired = await self.repository.transition_interaction(
                    session,
                    interaction_id=interaction.id,
                    status=ExternalChannelInteractionStatus.EXPIRED,
                    error_kind=None,
                    error_summary=None,
                    transitioned_at=now,
                )
                if expired is None:
                    raise RuntimeError(
                        "Selector interaction disappeared during expiry."
                    )
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="expired",
                    selector_interaction=expired,
                    binding=None,
                )
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=state.connection_id,
            )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=route_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
                or route is None
                or route.connection_id != connection.id
            ):
                raise ExternalChannelSelectorError("Selected Agent is unavailable.")
            if interaction.setup_claim_id is not None:
                return await self._select_setup_route(
                    session,
                    interaction=interaction,
                    state=state,
                    connection_id=connection.id,
                    requested_route=route,
                    principal_id=principal_id,
                )
            resource = await self.repository.lock_resource(
                session,
                resource_id=state.resource_id,
            )
            if resource is None or resource.connection_id != connection.id:
                raise ExternalChannelSelectorError("Selector source is unavailable.")
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            if binding is not None:
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="already_bound",
                    selector_interaction=interaction,
                    binding=binding,
                )
            if (
                await self.repository.get_active_block(
                    session,
                    agent_id=route.require_active_agent_id(),
                    principal_id=principal_id,
                )
                is not None
            ):
                raise ExternalChannelSelectorError("Selected Agent is unavailable.")
            if state.selected_route_id is not None:
                if state.selected_route_id != route.id:
                    raise ExternalChannelSelectorError("Selector route is immutable.")
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="already_selected",
                    selector_interaction=interaction,
                    binding=None,
                )
            updated = await self.repository.replace_interaction_projection(
                session,
                interaction_id=interaction.id,
                projection=projection_with_selector_state(
                    interaction.projection,
                    state.model_copy(update={"selected_route_id": route.id}),
                ),
            )
            if updated is None:
                raise RuntimeError("Selector interaction disappeared during selection.")
            await session.commit()
            return ExternalChannelSelectorSelection(
                status="selected",
                selector_interaction=updated,
                binding=None,
            )

    async def _select_setup_route(
        self,
        session: AsyncSession,
        *,
        interaction: ExternalChannelInteraction,
        state: ExternalChannelSelectorState,
        connection_id: str,
        requested_route: ExternalChannelAgentRoute,
        principal_id: str,
    ) -> ExternalChannelSelectorSelection:
        """Select only the parent-channel Agent without creating a Binding."""
        claim_id = interaction.setup_claim_id
        assert claim_id is not None
        claim = await self.repository.lock_setup_claim(
            session,
            claim_id=claim_id,
        )
        if (
            claim is None
            or claim.connection_id != connection_id
            or claim.status
            not in {
                ExternalChannelSetupClaimStatus.PENDING_AGENT,
                ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                ExternalChannelSetupClaimStatus.SELECTED,
                ExternalChannelSetupClaimStatus.COMPLETED,
            }
        ):
            raise ExternalChannelSelectorError("Setup interaction is unavailable.")
        source = await self.repository.lock_resource(
            session,
            resource_id=claim.source_resource_id,
        )
        if source is None or source.connection_id != connection_id:
            raise ExternalChannelSelectorError("Setup source is unavailable.")
        current_default = await self.repository.lock_routable_channel_default(
            session,
            connection_id=connection_id,
            provider_channel_id=claim.provider_parent_channel_id,
        )
        selected_route = current_default or requested_route
        if (
            await self.repository.get_active_block(
                session,
                agent_id=selected_route.require_active_agent_id(),
                principal_id=principal_id,
            )
            is not None
        ):
            raise ExternalChannelSelectorError("Selected Agent is unavailable.")
        grant = await self.repository.get_active_access_grant(
            session,
            agent_id=selected_route.require_active_agent_id(),
            principal_id=principal_id,
            agent_session_id=None,
        )
        if grant is None and not selected_route.open_access_enabled:
            raise ExternalChannelSelectorError("Selected Agent is unavailable.")
        if claim.status is ExternalChannelSetupClaimStatus.PENDING_AGENT:
            if current_default is None:
                await self.repository.create_channel_default(
                    session,
                    ExternalChannelChannelDefaultCreate(
                        connection_id=connection_id,
                        provider_channel_id=claim.provider_parent_channel_id,
                        route_id=selected_route.id,
                        status=ExternalChannelChannelDefaultStatus.ACTIVE,
                        configured_by_user_id=None,
                        configured_by_principal_id=principal_id,
                        invalidated_at=None,
                        invalidation_reason=None,
                    ),
                )
            assigned = await self.repository.assign_setup_claim_route(
                session,
                claim_id=claim.id,
                expected_claim_generation=claim.claim_generation,
                route_id=selected_route.id,
            )
            if assigned is None:
                raise ExternalChannelSelectorError(
                    "Setup Agent selection lost its current generation."
                )
        elif claim.route_id != selected_route.id:
            raise ExternalChannelSelectorError(
                "Setup Agent selection is no longer current."
            )
        updated = await self.repository.replace_interaction_projection(
            session,
            interaction_id=interaction.id,
            projection=projection_with_selector_state(
                interaction.projection,
                state.model_copy(update={"selected_route_id": selected_route.id}),
            ),
        )
        if updated is None:
            raise RuntimeError("Selector interaction disappeared during selection.")
        await session.commit()
        return ExternalChannelSelectorSelection(
            status="setup_pending_location",
            selector_interaction=updated,
            binding=None,
        )

    async def validate_discord_component_scope(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> None:
        """Revalidate Discord component actor and conversation scope."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=selector_interaction_id,
            )
            state = _selector_state(
                interaction,
                principal_id=principal_id,
                now=now,
            )
            assert interaction is not None
            connection = await self.repository.get_connection(
                session,
                connection_id=state.connection_id,
            )
            resource = await self.repository.get_resource(
                session,
                resource_id=state.resource_id,
            )
            if (
                connection is None
                or connection.provider is not ExternalChannelProvider.DISCORD
                or connection.app_mode is not ExternalChannelAppMode.MULTI
                or connection.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
                or resource is None
                or not isinstance(guild_id, str)
                or guild_id != connection.provider_tenant_id
                or not isinstance(channel_id, str)
            ):
                raise ExternalChannelSelectorError(
                    "Selector component scope is unavailable."
                )
            labels = resource.labels or {}
            scoped_channels = {
                value
                for key in (
                    "source_channel_id",
                    "parent_channel_id",
                    "root_message_id",
                    "thread_channel_id",
                    "delivery_channel_id",
                    "channel_id",
                    "thread_id",
                )
                if isinstance(value := labels.get(key), str) and value
            }
            if channel_id not in scoped_channels:
                raise ExternalChannelSelectorError(
                    "Selector component scope is unavailable."
                )

    async def _visible_candidates(
        self,
        session: AsyncSession,
        *,
        rows: list[ExternalChannelCatalogRoute],
        principal_id: str,
        setup_claim_id: str | None,
    ) -> list[ExternalChannelSelectorCandidate]:
        candidates: list[ExternalChannelSelectorCandidate] = []
        for row in rows:
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=row.route.require_active_agent_id(),
                principal_id=principal_id,
                agent_session_id=None,
            )
            if (
                setup_claim_id is not None
                and grant is None
                and not row.route.open_access_enabled
            ):
                continue
            candidates.append(
                ExternalChannelSelectorCandidate(
                    route_id=row.route.id,
                    agent_name=row.agent_name,
                    access=(
                        "available"
                        if grant is not None
                        or (
                            setup_claim_id is not None and row.route.open_access_enabled
                        )
                        else "access_required"
                    ),
                )
            )
        return candidates


def _selector_state(
    interaction: ExternalChannelInteraction | None,
    *,
    principal_id: str,
    now: datetime.datetime | None,
) -> ExternalChannelSelectorState:
    if (
        interaction is None
        or interaction.principal_id != principal_id
        or interaction.status
        in {
            ExternalChannelInteractionStatus.EXPIRED,
            ExternalChannelInteractionStatus.REJECTED,
            ExternalChannelInteractionStatus.FAILED,
        }
        or (now is not None and interaction.expires_at <= now)
    ):
        raise ExternalChannelSelectorError("Selector interaction is unavailable.")
    state = selector_state_from_interaction(interaction)
    if state.principal_id != principal_id:
        raise ExternalChannelSelectorError("Selector principal is unavailable.")
    return state
