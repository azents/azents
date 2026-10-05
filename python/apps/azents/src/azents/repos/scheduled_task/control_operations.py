"""Completed provider-control authority and atomic definition mutations."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.scheduled_task_control import (
    ScheduledTaskControlLocator,
    ScheduledTaskEditInput,
    ScheduledTaskProviderControlError,
    ScheduledTaskProviderControlResult,
    _provider_context_matches_binding,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.data import ExternalChannelInteraction
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.scheduled_task.data import ScheduledTask
from azents.repos.scheduled_task.definition import (
    RDBScheduledTaskAuthorityValidator,
    ScheduledTaskDefinitionRepository,
)
from azents.repos.scheduled_task.repository import ScheduledTaskRepository
from azents.repos.scheduled_task_cycle import ScheduledTaskCycleRepository


@dataclass
class ScheduledTaskProviderControlRepository:
    """Reload and reauthorize registered Scheduled Task provider controls."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    external_repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    task_repository: Annotated[
        ScheduledTaskRepository, Depends(ScheduledTaskRepository)
    ]
    cycle_repository: Annotated[
        ScheduledTaskCycleRepository, Depends(ScheduledTaskCycleRepository)
    ]
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]

    def _definition_repository(self) -> ScheduledTaskDefinitionRepository:
        return ScheduledTaskDefinitionRepository(
            repository=self.task_repository,
            cycle_repository=self.cycle_repository,
            mailbox_repository=self.mailbox_repository,
            authority_validator=RDBScheduledTaskAuthorityValidator(),
        )

    async def mutate(
        self,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
        origin_interaction_id: str | None,
        edit: ScheduledTaskEditInput | None,
        now: datetime.datetime,
    ) -> ScheduledTaskProviderControlResult:
        """Revalidate one claimed actor and apply exactly one current mutation."""
        if locator.action == "edit" and edit is None:
            raise ScheduledTaskProviderControlError(
                "Scheduled Task edit is incomplete."
            )
        if locator.action != "edit" and edit is not None:
            raise ScheduledTaskProviderControlError(
                "Scheduled Task cancellation is invalid."
            )
        async with self.session_manager() as session:
            definitions = self._definition_repository()
            candidate = await self.task_repository.get_by_id(session, locator.task_id)
            if candidate is None or candidate.binding_id != locator.binding_id:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            interaction = await self._authorize(
                session,
                interaction_id=interaction_id,
                locator=locator,
                task=candidate,
                provider_parent_channel_id=provider_parent_channel_id,
                provider_thread_resource_key=provider_thread_resource_key,
                origin_interaction_id=origin_interaction_id,
            )
            del interaction
            target = await definitions.lock_provider_mutation_target(
                session,
                task_id=locator.task_id,
                expected_binding_id=locator.binding_id,
            )
            if target is None or target.task != candidate:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            if locator.action in {"delete", "confirm_delete"}:
                deleted = await definitions.delete_locked_provider_target(
                    session,
                    target=target,
                    expected_binding_id=locator.binding_id,
                )
                if not deleted:
                    raise ScheduledTaskProviderControlError(
                        "Scheduled Task is no longer available."
                    )
                await session.write_session.commit()
                return ScheduledTaskProviderControlResult(
                    action="delete",
                    task=target.task,
                )
            assert edit is not None
            replacement = await definitions.replace_locked_provider_target(
                session,
                target=target,
                expected_binding_id=locator.binding_id,
                title=edit.title,
                objective=edit.objective,
                at=edit.at,
                cron=edit.cron,
                timezone=edit.timezone,
                binding_id=locator.binding_id,
                now=now,
            )
            if replacement is None:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task is no longer available."
                )
            await session.write_session.commit()
            return ScheduledTaskProviderControlResult(action="edit", task=replacement)

    async def load_for_control(
        self,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
    ) -> ScheduledTask:
        """Revalidate a claimed component before rendering its next control."""
        async with self.session_manager() as session:
            task = await self.task_repository.get_by_id(session, locator.task_id)
            if task is None or task.binding_id != locator.binding_id:
                raise ScheduledTaskProviderControlError(
                    "Scheduled Task control is unavailable."
                )
            await self._authorize(
                session,
                interaction_id=interaction_id,
                locator=locator,
                task=task,
                provider_parent_channel_id=provider_parent_channel_id,
                provider_thread_resource_key=provider_thread_resource_key,
                origin_interaction_id=None,
            )
            return task

    async def _authorize(
        self,
        session: WriteSession,
        *,
        interaction_id: str,
        locator: ScheduledTaskControlLocator,
        task: ScheduledTask,
        provider_parent_channel_id: str | None,
        provider_thread_resource_key: str | None,
        origin_interaction_id: str | None,
    ) -> ExternalChannelInteraction:
        interaction = await self.external_repository.lock_interaction(
            session, interaction_id=interaction_id
        )
        if (
            interaction is None
            or interaction.status is not ExternalChannelInteractionStatus.PROCESSING
            or interaction.principal_id is None
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        connection = await self.external_repository.get_connection_configuration(
            session, connection_id=interaction.connection_id
        )
        principal = await self.external_repository.get_principal(
            session, principal_id=interaction.principal_id
        )
        binding = await self.external_repository.lock_binding(
            session, binding_id=locator.binding_id
        )
        if (
            connection is None
            or connection.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
            or principal is None
            or principal.provider is not connection.provider
            or principal.provider_tenant_id != connection.provider_tenant_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
            or task is None
            or task.binding_id != locator.binding_id
            or binding is None
            or binding.disconnected_at is not None
            or binding.agent_session_id != task.session_id
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        resource = await self.external_repository.get_resource(
            session, resource_id=binding.resource_id
        )
        route = await self.external_repository.get_routable_route_by_binding_id(
            session, binding_id=binding.id
        )
        context_matches = resource is not None and _provider_context_matches_binding(
            resource_type=resource.resource_type,
            resource_key=resource.provider_resource_key,
            provider_parent_channel_id=provider_parent_channel_id,
            provider_thread_resource_key=provider_thread_resource_key,
        )
        if not context_matches and resource is not None:
            context_matches = await self._slack_modal_origin_matches_binding(
                session,
                origin_interaction_id=origin_interaction_id,
                interaction=interaction,
                provider=connection.provider,
                provider_tenant_id=connection.provider_tenant_id,
                resource_key=resource.provider_resource_key,
            )
        if (
            resource is None
            or resource.connection_id != connection.id
            or route is None
            or route.id != binding.route_id
            or route.agent_id != task.agent_id
            or not context_matches
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        if (
            await self.external_repository.get_active_block(
                session, agent_id=task.agent_id, principal_id=principal.id
            )
            is not None
        ):
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        grant = await self.external_repository.get_active_access_grant(
            session,
            agent_id=task.agent_id,
            principal_id=principal.id,
            agent_session_id=task.session_id,
        )
        if grant is None and not route.open_access_enabled:
            raise ScheduledTaskProviderControlError(
                "Scheduled Task control is unavailable."
            )
        return interaction

    async def _slack_modal_origin_matches_binding(
        self,
        session: WriteSession,
        *,
        origin_interaction_id: str | None,
        interaction: ExternalChannelInteraction,
        provider: ExternalChannelProvider,
        provider_tenant_id: str | None,
        resource_key: str,
    ) -> bool:
        """Require a signed Slack modal to originate from the exact prior thread."""
        if origin_interaction_id is None:
            return False
        origin = await self.external_repository.lock_interaction(
            session,
            interaction_id=origin_interaction_id,
        )
        if (
            origin is None
            or origin.id == interaction.id
            or origin.connection_id != interaction.connection_id
            or origin.principal_id != interaction.principal_id
            or origin.status
            not in {
                ExternalChannelInteractionStatus.PROCESSING,
                ExternalChannelInteractionStatus.COMPLETED,
            }
            or provider is not ExternalChannelProvider.SLACK
            or provider_tenant_id is None
            or origin.resource_correlation_key is None
        ):
            return False
        return resource_key == (
            f"slack:{provider_tenant_id}:{origin.resource_correlation_key}"
        )
