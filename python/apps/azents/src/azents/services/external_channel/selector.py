"""Durable Multi App selector catalog and immutable route selection."""

import datetime
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelCatalogRoute,
    ExternalChannelConversationAdmission,
)
from azents.repos.external_channel.repository import ExternalChannelRepository

_SELECTOR_PAGE_SIZE = 20


class ExternalChannelSelectorError(ValueError):
    """A selector request does not match current durable routing state."""


@dataclass(frozen=True)
class ExternalChannelSelectorCandidate:
    """One current visible Agent candidate without a provider-supplied authority."""

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
    """One immutable selection result or its pre-existing binding winner."""

    status: Literal["selected", "already_selected", "already_bound", "expired"]
    admission: ExternalChannelConversationAdmission
    binding: ExternalChannelBinding | None


@dataclass
class ExternalChannelSelectorService:
    """Project and select only current eligible Multi App routes."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]

    async def project_catalog(
        self,
        *,
        admission_id: str,
        principal_id: str,
        search: str | None,
        offset: int,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorCatalog:
        """Load one complete bounded catalog page from trusted admission state."""
        async with self.session_manager() as session:
            admission = await self.repository.get_conversation_admission(
                session,
                admission_id=admission_id,
            )
            if admission is None or admission.initiating_principal_id != principal_id:
                raise ExternalChannelSelectorError("Selector admission is unavailable.")
            connection = await self.repository.get_connection(
                session,
                connection_id=admission.connection_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
                or admission.status
                is not ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                or admission.expires_at <= now
            ):
                raise ExternalChannelSelectorError("Selector admission is unavailable.")
            principal = await self.repository.get_principal(
                session,
                principal_id=principal_id,
            )
            if principal is None or principal.author_type not in {
                ExternalChannelPrincipalAuthorType.HUMAN,
                ExternalChannelPrincipalAuthorType.BOT,
            }:
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
            visible_rows = rows[:_SELECTOR_PAGE_SIZE]
            candidates = await self._visible_candidates(
                session,
                rows=visible_rows,
                principal_id=principal_id,
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
        admission_id: str,
        principal_id: str,
        route_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelSelectorSelection:
        """Apply one immutable trusted route choice under the routing lock order."""
        async with self.session_manager() as session:
            snapshot = await self.repository.get_conversation_admission(
                session,
                admission_id=admission_id,
            )
            if snapshot is None:
                raise ExternalChannelSelectorError("Selector admission is unavailable.")
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=snapshot.connection_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
            ):
                raise ExternalChannelSelectorError(
                    "Selector connection is unavailable."
                )
            route = await self.repository.get_routable_route_by_id(
                session,
                route_id=route_id,
            )
            if route is None or route.connection_id != connection.id:
                raise ExternalChannelSelectorError("Selected Agent is unavailable.")
            principal = await self.repository.get_principal(
                session,
                principal_id=principal_id,
            )
            if (
                principal is None
                or principal.author_type
                not in {
                    ExternalChannelPrincipalAuthorType.HUMAN,
                    ExternalChannelPrincipalAuthorType.BOT,
                }
                or (
                    principal.author_type is ExternalChannelPrincipalAuthorType.BOT
                    and not route.allow_bot_messages
                )
            ):
                raise ExternalChannelSelectorError("Selected Agent is unavailable.")
            resource = await self.repository.lock_resource(
                session,
                resource_id=snapshot.resource_id,
            )
            if resource is None or resource.connection_id != connection.id:
                raise ExternalChannelSelectorError("Selector source is unavailable.")
            binding = await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            admission = await self.repository.lock_open_conversation_admission(
                session,
                resource_id=resource.id,
            )
            if admission is None or admission.id != snapshot.id:
                raise ExternalChannelSelectorError("Selector admission changed.")
            if admission.initiating_principal_id != principal_id:
                raise ExternalChannelSelectorError("Selector principal is unavailable.")
            if admission.expires_at <= now:
                expired = await self.repository.transition_conversation_admission(
                    session,
                    admission_id=admission.id,
                    status=ExternalChannelConversationAdmissionStatus.EXPIRED,
                    selected_route_id=admission.selected_route_id,
                )
                if expired is None:
                    raise RuntimeError("Selector admission disappeared during expiry.")
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="expired",
                    admission=expired,
                    binding=binding,
                )
            if binding is not None:
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="already_bound",
                    admission=admission,
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
            if admission.selected_route_id is not None:
                if admission.selected_route_id != route.id:
                    raise ExternalChannelSelectorError("Selector route is immutable.")
                await session.commit()
                return ExternalChannelSelectorSelection(
                    status="already_selected",
                    admission=admission,
                    binding=None,
                )
            selected = await self.repository.transition_conversation_admission(
                session,
                admission_id=admission.id,
                status=ExternalChannelConversationAdmissionStatus.SELECTED,
                selected_route_id=route.id,
            )
            if selected is None:
                raise RuntimeError("Selector admission disappeared during selection.")
            await session.commit()
            return ExternalChannelSelectorSelection(
                status="selected",
                admission=selected,
                binding=None,
            )

    async def validate_discord_component_scope(
        self,
        *,
        admission_id: str,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> None:
        """Revalidate Discord component actor and conversation scope."""
        async with self.session_manager() as session:
            admission = await self.repository.get_conversation_admission(
                session,
                admission_id=admission_id,
            )
            if admission is None or admission.initiating_principal_id != principal_id:
                raise ExternalChannelSelectorError("Selector admission is unavailable.")
            connection = await self.repository.get_connection(
                session,
                connection_id=admission.connection_id,
            )
            resource = await self.repository.get_resource(
                session,
                resource_id=admission.resource_id,
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
                or admission.status
                is not ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                or admission.expires_at <= now
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
    ) -> list[ExternalChannelSelectorCandidate]:
        """Exclude hard-blocked Agents and label the remaining current policy state."""
        candidates: list[ExternalChannelSelectorCandidate] = []
        for row in rows:
            agent_id = row.route.require_active_agent_id()
            grant = await self.repository.get_active_access_grant(
                session,
                agent_id=agent_id,
                principal_id=principal_id,
                agent_session_id=None,
            )
            candidates.append(
                ExternalChannelSelectorCandidate(
                    route_id=row.route.id,
                    agent_name=row.agent_name,
                    access="available" if grant is not None else "access_required",
                )
            )
        return candidates
