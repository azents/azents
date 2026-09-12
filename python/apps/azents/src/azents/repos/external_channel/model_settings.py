"""Repository-owned private shared-model settings transactions."""

import datetime
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, NamedTuple, TypeVar

import sqlalchemy as sa
from azcommon.uuid import uuid7
from fastapi import Depends
from pydantic import TypeAdapter
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import SelectableModelOption
from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelConnectionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelRouteCatalogStatus,
)
from azents.core.external_model_settings import (
    ExternalModelActorContext,
    ExternalModelApplied,
    ExternalModelBusy,
    ExternalModelCancelResult,
    ExternalModelDraft,
    ExternalModelDraftCancelled,
    ExternalModelDraftSelection,
    ExternalModelEditor,
    ExternalModelEditorReady,
    ExternalModelEditorResult,
    ExternalModelNoticeOutcome,
    ExternalModelNoticePlan,
    ExternalModelOption,
    ExternalModelOptionPage,
    ExternalModelRejected,
    ExternalModelSettingsRejectionCode,
    ExternalModelStale,
    ExternalModelTargetContext,
)
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    SessionAppliedInferenceProfile,
    validate_requested_profile_against_options,
)
from azents.core.model_execution_options import (
    MODEL_EXECUTION_OPTION_DEFINITIONS,
    ModelExecutionOptionDefinition,
    ModelExecutionOptionId,
    list_model_execution_option_definitions,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_model_settings import (
    RDBExternalModelDraft,
    RDBExternalModelMutation,
)
from azents.rdb.models.user import RDBUser
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.external_account_link import ExternalAccountLinkRepository
from azents.repos.external_account_link.data import ExternalAccountLink
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.session_model_profile.repository import SessionModelProfileRepository

from .model_settings_data import (
    ExternalModelApplyCommit,
    ExternalModelNoticeDeliveryContext,
)

_DRAFT_LIFETIME = datetime.timedelta(minutes=15)
_LOCK_TIMEOUT = "250ms"
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
_EXECUTION_OPTION_IDS = TypeAdapter(list[ModelExecutionOptionId])
T = TypeVar("T")


@dataclass(frozen=True)
class _AuthorizedModelTarget:
    connection: RDBExternalChannelConnection
    principal: RDBExternalChannelPrincipal
    binding: RDBExternalChannelBinding
    resource: RDBExternalChannelResource
    route: RDBExternalChannelAgentRoute
    session: AgentSession
    agent: Agent
    link: ExternalAccountLink


@dataclass(frozen=True)
class _AuthorizationResult:
    target: _AuthorizedModelTarget | None
    rejection: ExternalModelRejected | None


class _ExternalModelNoticeTarget(NamedTuple):
    """Structured result returned by `_notice_target`."""

    provider_conversation_id: str
    provider_thread_id: str | None


class ExternalModelSettingsRepository:
    """Own native draft, authorization, mutation, and retry transactions."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        external_channel_repository: Annotated[
            ExternalChannelRepository, Depends(ExternalChannelRepository.create)
        ],
        external_account_link_repository: Annotated[
            ExternalAccountLinkRepository, Depends(ExternalAccountLinkRepository)
        ],
        session_model_profile_repository: Annotated[
            SessionModelProfileRepository, Depends(SessionModelProfileRepository)
        ],
        agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
        agent_session_repository: Annotated[
            AgentSessionRepository, Depends(AgentSessionRepository)
        ],
    ) -> None:
        self.session_manager = session_manager
        self.external_channel_repository = external_channel_repository
        self.external_account_link_repository = external_account_link_repository
        self.session_model_profile_repository = session_model_profile_repository
        self.agent_repository = agent_repository
        self.agent_session_repository = agent_session_repository

    async def open_editor(
        self,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
        owner_interaction_key: str,
        now: datetime.datetime,
        offset: int,
        limit: int,
    ) -> ExternalModelEditorResult:
        """Create or replay one authorized actor-private draft."""
        self._validate_page(offset=offset, limit=limit)

        async def operation(session: AsyncSession) -> ExternalModelEditorResult:
            authorization = await self._authorize(
                session,
                actor=actor,
                target=target,
            )
            if authorization.rejection is not None:
                return authorization.rejection
            authorized = self._require_authorized(authorization)
            existing = await session.scalar(
                sa.select(RDBExternalModelDraft)
                .where(
                    RDBExternalModelDraft.connection_id == actor.connection_id,
                    RDBExternalModelDraft.owner_interaction_key
                    == owner_interaction_key,
                )
                .with_for_update(nowait=True)
            )
            if existing is not None:
                rejection = self._validate_draft(
                    existing,
                    actor=actor,
                    target=target,
                    now=now,
                    allow_applied=False,
                )
                if rejection is not None:
                    return rejection
                self._refresh_options(existing, authorized.agent)
                await session.flush()
                return ExternalModelEditorReady(
                    editor=self._editor(
                        existing,
                        authorized.session,
                        offset=offset,
                        limit=limit,
                    )
                )
            draft = self._new_draft(
                actor=actor,
                target=target,
                authorized=authorized,
                owner_interaction_key=owner_interaction_key,
                now=now,
            )
            session.add(draft)
            await session.flush()
            return ExternalModelEditorReady(
                editor=self._editor(
                    draft,
                    authorized.session,
                    offset=offset,
                    limit=limit,
                )
            )

        return await self._run_with_retry(operation, ExternalModelBusy())

    async def update_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        selection: ExternalModelDraftSelection,
        now: datetime.datetime,
        offset: int,
        limit: int,
    ) -> ExternalModelEditorResult:
        """Update only one live private draft and re-render current capabilities."""
        self._validate_page(offset=offset, limit=limit)

        async def operation(session: AsyncSession) -> ExternalModelEditorResult:
            draft = await self._lock_draft(session, draft_id=draft_id)
            if draft is None:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                )
            target = self._draft_target(draft)
            rejection = self._validate_draft(
                draft,
                actor=actor,
                target=target,
                now=now,
                allow_applied=False,
            )
            if rejection is not None:
                return rejection
            authorization = await self._authorize(session, actor=actor, target=target)
            if authorization.rejection is not None:
                return authorization.rejection
            authorized = self._require_authorized(authorization)
            self._refresh_options(draft, authorized.agent)
            option = self._snapshot_option(draft, selection.option_id)
            if option is None:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.MODEL_OPTION_UNAVAILABLE
                )
            if selection.option_id != draft.selected_option_id:
                reasoning_effort = None
                execution_options: list[ModelExecutionOptionId] = []
            else:
                reasoning_effort = selection.reasoning_effort
                execution_options = selection.enabled_execution_options
            profile = RequestedInferenceProfile(
                model_target_label=self._option_target_label(option),
                reasoning_effort=reasoning_effort,
                enabled_execution_options=execution_options,
            )
            try:
                validate_requested_profile_against_options(
                    authorized.agent.selectable_model_options,
                    profile,
                )
            except ValueError:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.MODEL_OPTION_UNAVAILABLE
                )
            draft.selected_option_id = selection.option_id
            draft.selected_model_target_label = profile.model_target_label
            draft.selected_reasoning_effort = profile.reasoning_effort
            draft.selected_enabled_execution_options = [
                value.value for value in profile.enabled_execution_options
            ]
            await session.flush()
            return ExternalModelEditorReady(
                editor=self._editor(
                    draft,
                    authorized.session,
                    offset=offset,
                    limit=limit,
                )
            )

        return await self._run_with_retry(operation, ExternalModelBusy())

    async def page_options(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        now: datetime.datetime,
        offset: int,
        limit: int,
    ) -> ExternalModelEditorResult:
        """Refresh authority and return one bounded private option page."""
        self._validate_page(offset=offset, limit=limit)

        async def operation(session: AsyncSession) -> ExternalModelEditorResult:
            draft = await self._lock_draft(session, draft_id=draft_id)
            if draft is None:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                )
            target = self._draft_target(draft)
            rejection = self._validate_draft(
                draft,
                actor=actor,
                target=target,
                now=now,
                allow_applied=False,
            )
            if rejection is not None:
                return rejection
            authorization = await self._authorize(session, actor=actor, target=target)
            if authorization.rejection is not None:
                return authorization.rejection
            authorized = self._require_authorized(authorization)
            self._refresh_options(draft, authorized.agent)
            await session.flush()
            return ExternalModelEditorReady(
                editor=self._editor(
                    draft,
                    authorized.session,
                    offset=offset,
                    limit=limit,
                )
            )

        return await self._run_with_retry(operation, ExternalModelBusy())

    async def cancel_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        now: datetime.datetime,
    ) -> ExternalModelCancelResult:
        """Idempotently terminalize only the exact actor-owned draft."""

        async def operation(session: AsyncSession) -> ExternalModelCancelResult:
            draft = await self._lock_draft(session, draft_id=draft_id)
            if draft is None:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                )
            if not self._actor_matches(draft, actor):
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.ACTOR_MISMATCH
                )
            if draft.applied_at is not None:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                )
            if draft.expires_at <= now:
                return ExternalModelRejected(
                    code=ExternalModelSettingsRejectionCode.DRAFT_EXPIRED
                )
            if draft.cancelled_at is None:
                draft.cancelled_at = now
                await session.flush()
            return ExternalModelDraftCancelled(draft_id=draft.id)

        return await self._run_with_retry(operation, ExternalModelBusy())

    async def apply_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        draft_id: str,
        expected_selection_fingerprint: str,
        apply_interaction_key: str,
        now: datetime.datetime,
    ) -> ExternalModelApplyCommit:
        """Apply one generation-fenced draft and preclaim one unknown notice."""

        async def operation(session: AsyncSession) -> ExternalModelApplyCommit:
            draft = await self._lock_draft(session, draft_id=draft_id)
            if draft is None:
                return ExternalModelApplyCommit(
                    result=ExternalModelRejected(
                        code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                    ),
                    notice_plan=None,
                )
            target = self._draft_target(draft)
            rejection = self._validate_draft(
                draft,
                actor=actor,
                target=target,
                now=now,
                allow_applied=True,
            )
            if rejection is not None:
                return ExternalModelApplyCommit(result=rejection, notice_plan=None)
            authorization = await self._authorize(session, actor=actor, target=target)
            if authorization.rejection is not None:
                return ExternalModelApplyCommit(
                    result=authorization.rejection,
                    notice_plan=None,
                )
            authorized = self._require_authorized(authorization)
            existing = await session.scalar(
                sa.select(RDBExternalModelMutation)
                .where(
                    RDBExternalModelMutation.provider == actor.provider,
                    RDBExternalModelMutation.connection_id == actor.connection_id,
                    RDBExternalModelMutation.apply_interaction_key
                    == apply_interaction_key,
                )
                .with_for_update(nowait=True)
            )
            if existing is not None:
                if self._selection_fingerprint(
                    draft
                ) != expected_selection_fingerprint or not self._mutation_matches(
                    existing,
                    actor=actor,
                    target=target,
                    user_id=authorized.link.user_id,
                ):
                    return ExternalModelApplyCommit(
                        result=ExternalModelRejected(
                            code=ExternalModelSettingsRejectionCode.ACTOR_MISMATCH
                        ),
                        notice_plan=None,
                    )
                return ExternalModelApplyCommit(
                    result=ExternalModelApplied(
                        editor=self._editor(
                            draft,
                            authorized.session,
                            offset=0,
                            limit=10,
                        ),
                        created=False,
                        mutation_id=existing.id,
                        notice_outcome=existing.notice_outcome,
                    ),
                    notice_plan=None,
                )
            if draft.applied_at is not None:
                return ExternalModelApplyCommit(
                    result=ExternalModelRejected(
                        code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
                    ),
                    notice_plan=None,
                )
            previous_fingerprint = self._selection_fingerprint(draft)
            self._refresh_options(draft, authorized.agent)
            if (
                authorized.session.applied_profile_generation
                != draft.expected_generation
            ):
                self._reset_stale_draft(draft, authorized.session, authorized.agent)
            refreshed_fingerprint = self._selection_fingerprint(draft)
            if (
                refreshed_fingerprint != expected_selection_fingerprint
                or refreshed_fingerprint != previous_fingerprint
            ):
                await session.flush()
                return ExternalModelApplyCommit(
                    result=ExternalModelStale(
                        editor=self._editor(
                            draft,
                            authorized.session,
                            offset=0,
                            limit=10,
                        )
                    ),
                    notice_plan=None,
                )
            profile = RequestedInferenceProfile(
                model_target_label=draft.selected_model_target_label,
                reasoning_effort=draft.selected_reasoning_effort,
                enabled_execution_options=_EXECUTION_OPTION_IDS.validate_python(
                    draft.selected_enabled_execution_options
                ),
            )
            try:
                selected = validate_requested_profile_against_options(
                    authorized.agent.selectable_model_options,
                    profile,
                )
            except ValueError:
                return ExternalModelApplyCommit(
                    result=ExternalModelRejected(
                        code=ExternalModelSettingsRejectionCode.MODEL_OPTION_UNAVAILABLE
                    ),
                    notice_plan=None,
                )
            old_profile = authorized.session.applied_inference_profile
            updated = await self.agent_session_repository.set_applied_inference_profile(
                session,
                session_id=authorized.session.id,
                model_target_label=profile.model_target_label,
                reasoning_effort=profile.reasoning_effort,
                enabled_execution_options=profile.enabled_execution_options,
            )
            resulting_generation = updated.applied_profile_generation
            if resulting_generation != draft.expected_generation + 1:
                raise RuntimeError("Applied profile generation did not advance once")
            provider_conversation_id, provider_thread_id = self._notice_target(
                authorized
            )
            mutation = RDBExternalModelMutation(
                provider=actor.provider,
                connection_id=actor.connection_id,
                apply_interaction_key=apply_interaction_key,
                principal_id=actor.principal_id,
                principal_id_snapshot=actor.principal_id,
                provider_tenant_id_snapshot=actor.provider_tenant_id,
                provider_user_id_snapshot=actor.provider_user_id,
                provider_tenant_display_label_snapshot=(
                    authorized.link.provider_tenant_display_label
                ),
                actor_display_name_snapshot=authorized.link.provider_display_label,
                link_id=authorized.link.id,
                link_id_snapshot=authorized.link.id,
                user_id=authorized.link.user_id,
                user_id_snapshot=authorized.link.user_id,
                binding_id=authorized.binding.id,
                binding_id_snapshot=authorized.binding.id,
                session_id=authorized.session.id,
                agent_id=authorized.agent.id,
                agent_id_snapshot=authorized.agent.id,
                old_model_target_label=(
                    None if old_profile is None else old_profile.model_target_label
                ),
                old_reasoning_effort=(
                    None if old_profile is None else old_profile.reasoning_effort
                ),
                old_enabled_execution_options=(
                    []
                    if old_profile is None
                    else [
                        value.value for value in old_profile.enabled_execution_options
                    ]
                ),
                new_model_target_label=profile.model_target_label,
                new_model_display_name=selected.model_selection.model_display_name,
                new_reasoning_effort=profile.reasoning_effort,
                new_enabled_execution_options=[
                    value.value for value in profile.enabled_execution_options
                ],
                expected_generation=draft.expected_generation,
                resulting_generation=resulting_generation,
                provider_conversation_id=provider_conversation_id,
                provider_thread_id=provider_thread_id,
                notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
                notice_attempted_at=None,
                notice_error_summary=None,
            )
            session.add(mutation)
            draft.applied_at = now
            await session.flush()
            updated_editor = self._editor(
                draft,
                updated,
                offset=0,
                limit=10,
            )
            plan = ExternalModelNoticePlan(
                mutation_id=mutation.id,
                provider=actor.provider,
                connection_id=actor.connection_id,
                provider_conversation_id=provider_conversation_id,
                provider_thread_id=provider_thread_id,
                actor_display_name=authorized.link.provider_display_label,
                model_label=profile.model_target_label,
                model_display_name=selected.model_selection.model_display_name,
                reasoning_effort=profile.reasoning_effort,
                enabled_execution_option_labels=[
                    definition.label
                    for definition in list_model_execution_option_definitions(
                        provider=selected.model_selection.provider,
                        supported=profile.enabled_execution_options,
                    )
                ],
            )
            return ExternalModelApplyCommit(
                result=ExternalModelApplied(
                    editor=updated_editor,
                    created=True,
                    mutation_id=mutation.id,
                    notice_outcome=ExternalModelNoticeOutcome.UNKNOWN,
                ),
                notice_plan=plan,
            )

        return await self._run_with_retry(
            operation,
            ExternalModelApplyCommit(result=ExternalModelBusy(), notice_plan=None),
        )

    async def get_notice_delivery_context(
        self,
        *,
        mutation_id: str,
    ) -> ExternalModelNoticeDeliveryContext | None:
        """Load one committed preclaimed notice and its encrypted credentials."""
        async with self.session_manager() as session:
            row = (
                await session.execute(
                    sa.select(RDBExternalModelMutation, RDBExternalChannelConnection)
                    .join(
                        RDBExternalChannelConnection,
                        RDBExternalChannelConnection.id
                        == RDBExternalModelMutation.connection_id,
                    )
                    .where(RDBExternalModelMutation.id == mutation_id)
                )
            ).one_or_none()
            if row is None:
                return None
            mutation, connection = row
            if (
                mutation.notice_outcome is not ExternalModelNoticeOutcome.UNKNOWN
                or mutation.notice_attempted_at is not None
                or connection.encrypted_credentials is None
            ):
                return None
            return ExternalModelNoticeDeliveryContext(
                plan=self._notice_plan(mutation),
                encrypted_credentials=connection.encrypted_credentials,
            )

    async def record_notice_outcome(
        self,
        *,
        mutation_id: str,
        outcome: ExternalModelNoticeOutcome,
        attempted_at: datetime.datetime,
        error_summary: str | None,
    ) -> ExternalModelNoticeOutcome:
        """Record one terminal delivery observation without retry scheduling."""
        async with self.session_manager() as session:
            result = await session.execute(
                sa.update(RDBExternalModelMutation)
                .where(
                    RDBExternalModelMutation.id == mutation_id,
                    RDBExternalModelMutation.notice_outcome
                    == ExternalModelNoticeOutcome.UNKNOWN,
                    RDBExternalModelMutation.notice_attempted_at.is_(None),
                )
                .values(
                    notice_outcome=outcome,
                    notice_attempted_at=attempted_at,
                    notice_error_summary=(
                        None if error_summary is None else error_summary[:255]
                    ),
                )
                .returning(RDBExternalModelMutation.notice_outcome)
            )
            stored = result.scalar_one_or_none()
            if stored is not None:
                return stored
            existing = await session.scalar(
                sa.select(RDBExternalModelMutation.notice_outcome).where(
                    RDBExternalModelMutation.id == mutation_id
                )
            )
            if existing is None:
                raise ValueError("External model mutation not found")
            return existing

    async def _run_with_retry(
        self,
        operation: Callable[[AsyncSession], Awaitable[T]],
        busy_result: T,
    ) -> T:
        for _attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session_manager() as session:
                    await session.execute(
                        sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'")
                    )
                    return await operation(session)
            except DBAPIError as error:
                if not self._retryable(error):
                    raise
        return busy_result

    async def _authorize(
        self,
        session: AsyncSession,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
    ) -> _AuthorizationResult:
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == actor.connection_id)
            .with_for_update(nowait=True)
        )
        if (
            connection is None
            or connection.provider is not actor.provider
            or connection.configuration_generation != actor.configuration_generation
            or connection.provider_tenant_id != actor.provider_tenant_id
            or connection.status
            not in {
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            }
        ):
            return self._rejected(ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE)
        principal = await session.scalar(
            sa.select(RDBExternalChannelPrincipal)
            .where(RDBExternalChannelPrincipal.id == actor.principal_id)
            .with_for_update(nowait=True)
        )
        if (
            principal is None
            or principal.provider is not actor.provider
            or principal.provider_tenant_id != actor.provider_tenant_id
            or principal.provider_user_id != actor.provider_user_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            return self._rejected(ExternalModelSettingsRejectionCode.ACTOR_MISMATCH)
        binding = await session.scalar(
            sa.select(RDBExternalChannelBinding)
            .where(RDBExternalChannelBinding.id == target.binding_id)
            .with_for_update(nowait=True)
        )
        if (
            binding is None
            or binding.disconnected_at is not None
            or binding.agent_session_id != target.session_id
        ):
            return self._rejected(ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE)
        resource = await session.scalar(
            sa.select(RDBExternalChannelResource)
            .where(RDBExternalChannelResource.id == binding.resource_id)
            .with_for_update(nowait=True)
        )
        route = await session.scalar(
            sa.select(RDBExternalChannelAgentRoute)
            .where(RDBExternalChannelAgentRoute.id == binding.route_id)
            .with_for_update(nowait=True)
        )
        if (
            resource is None
            or resource.connection_id != connection.id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or route is None
            or route.connection_id != connection.id
            or route.agent_id != target.agent_id
            or route.catalog_status is not ExternalChannelRouteCatalogStatus.AVAILABLE
        ):
            return self._rejected(ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE)
        identity_scope = (
            "global"
            if actor.provider is ExternalChannelProvider.DISCORD
            else actor.provider_tenant_id
        )
        link = await self.external_account_link_repository.lock_active_link(
            session,
            workspace_id=connection.workspace_id,
            provider=actor.provider,
            identity_scope=identity_scope,
            provider_user_id=actor.provider_user_id,
            nowait=True,
        )
        if link is None:
            return self._rejected(ExternalModelSettingsRejectionCode.LINK_REQUIRED)
        user = await session.scalar(
            sa.select(RDBUser)
            .where(RDBUser.id == link.user_id)
            .with_for_update(nowait=True)
        )
        if user is None or user.access_disabled_at is not None:
            return self._rejected(
                ExternalModelSettingsRejectionCode.ACCOUNT_UNAVAILABLE
            )
        try:
            agent_session = (
                await self.session_model_profile_repository.lock_writable_root(
                    session,
                    agent_id=target.agent_id,
                    session_id=target.session_id,
                    user_id=link.user_id,
                    nowait=True,
                )
            )
        except ValueError as error:
            if "session access" in str(error):
                return self._rejected(
                    ExternalModelSettingsRejectionCode.MEMBERSHIP_REQUIRED
                )
            return self._rejected(ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE)
        agent = await self.agent_repository.lock_by_id_nowait(
            session,
            target.agent_id,
        )
        if (
            agent is None
            or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            or agent.workspace_id != connection.workspace_id
            or agent.workspace_id != agent_session.workspace_id
        ):
            return self._rejected(ExternalModelSettingsRejectionCode.TARGET_UNAVAILABLE)
        fence = (
            self.external_channel_repository.acquire_principal_agent_authorization_fence
        )
        acquired = await fence(
            session,
            agent_id=agent.id,
            principal_id=principal.id,
            nowait=True,
        )
        if not acquired:
            raise self._lock_not_available()
        block = await session.scalar(
            sa.select(RDBExternalChannelBlock)
            .where(
                RDBExternalChannelBlock.agent_id == agent.id,
                RDBExternalChannelBlock.principal_id == principal.id,
                RDBExternalChannelBlock.removed_at.is_(None),
            )
            .with_for_update(nowait=True)
        )
        if block is not None:
            return self._rejected(
                ExternalModelSettingsRejectionCode.PARTICIPATION_DENIED
            )
        grant = await session.scalar(
            sa.select(RDBExternalChannelAccessGrant)
            .where(
                RDBExternalChannelAccessGrant.agent_id == agent.id,
                RDBExternalChannelAccessGrant.principal_id == principal.id,
                RDBExternalChannelAccessGrant.revoked_at.is_(None),
                sa.or_(
                    sa.and_(
                        RDBExternalChannelAccessGrant.scope
                        == ExternalChannelAccessGrantScope.SESSION,
                        RDBExternalChannelAccessGrant.agent_session_id
                        == agent_session.id,
                    ),
                    sa.and_(
                        RDBExternalChannelAccessGrant.scope
                        == ExternalChannelAccessGrantScope.AGENT,
                        RDBExternalChannelAccessGrant.agent_session_id.is_(None),
                    ),
                ),
            )
            .order_by(
                sa.case(
                    (
                        RDBExternalChannelAccessGrant.scope
                        == ExternalChannelAccessGrantScope.SESSION,
                        0,
                    ),
                    else_=1,
                )
            )
            .limit(1)
            .with_for_update(nowait=True)
        )
        if grant is None and not route.open_access_enabled:
            return self._rejected(
                ExternalModelSettingsRejectionCode.PARTICIPATION_DENIED
            )
        return _AuthorizationResult(
            target=_AuthorizedModelTarget(
                connection=connection,
                principal=principal,
                binding=binding,
                resource=resource,
                route=route,
                session=agent_session,
                agent=agent,
                link=link,
            ),
            rejection=None,
        )

    def _new_draft(
        self,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
        authorized: _AuthorizedModelTarget,
        owner_interaction_key: str,
        now: datetime.datetime,
    ) -> RDBExternalModelDraft:
        options = self._options_snapshot(authorized.agent, previous=())
        profile = authorized.session.applied_inference_profile
        selected_target = (
            authorized.agent.main_model_label
            if profile is None
            else profile.model_target_label
        )
        selected_option = self._option_for_target(options, selected_target)
        if selected_option is None:
            selected_option = options[0]
            profile = None
        return RDBExternalModelDraft(
            provider=actor.provider,
            connection_id=actor.connection_id,
            principal_id=actor.principal_id,
            link_id=authorized.link.id,
            link_id_snapshot=authorized.link.id,
            user_id=authorized.link.user_id,
            user_id_snapshot=authorized.link.user_id,
            binding_id=target.binding_id,
            session_id=target.session_id,
            agent_id=target.agent_id,
            owner_interaction_key=owner_interaction_key,
            expected_generation=authorized.session.applied_profile_generation,
            options_snapshot=options,
            selected_option_id=self._option_id(selected_option),
            selected_model_target_label=self._option_target_label(selected_option),
            selected_reasoning_effort=(
                None if profile is None else profile.reasoning_effort
            ),
            selected_enabled_execution_options=(
                []
                if profile is None
                else [value.value for value in profile.enabled_execution_options]
            ),
            scope_label=self._scope_label(authorized.resource),
            expires_at=now + _DRAFT_LIFETIME,
            cancelled_at=None,
            applied_at=None,
        )

    def _refresh_options(self, draft: RDBExternalModelDraft, agent: Agent) -> None:
        options = self._options_snapshot(agent, previous=draft.options_snapshot)
        selected = self._option_for_target(
            options,
            draft.selected_model_target_label,
        )
        if selected is None:
            selected = self._option_for_target(options, agent.main_model_label)
            if selected is None:
                selected = options[0]
            draft.selected_option_id = self._option_id(selected)
            draft.selected_model_target_label = self._option_target_label(selected)
            draft.selected_reasoning_effort = None
            draft.selected_enabled_execution_options = []
        else:
            draft.selected_option_id = self._option_id(selected)
        draft.options_snapshot = options

    def _reset_stale_draft(
        self,
        draft: RDBExternalModelDraft,
        session: AgentSession,
        agent: Agent,
    ) -> None:
        draft.expected_generation = session.applied_profile_generation
        profile = session.applied_inference_profile
        target_label = (
            agent.main_model_label if profile is None else profile.model_target_label
        )
        selected = self._option_for_target(draft.options_snapshot, target_label)
        if selected is None:
            selected = draft.options_snapshot[0]
            profile = None
        draft.selected_option_id = self._option_id(selected)
        draft.selected_model_target_label = self._option_target_label(selected)
        draft.selected_reasoning_effort = (
            None if profile is None else profile.reasoning_effort
        )
        draft.selected_enabled_execution_options = (
            []
            if profile is None
            else [value.value for value in profile.enabled_execution_options]
        )

    def _options_snapshot(
        self,
        agent: Agent,
        *,
        previous: list[dict[str, object]] | tuple[()],
    ) -> list[dict[str, object]]:
        old_ids = {
            self._option_target_label(option): self._option_id(option)
            for option in previous
        }
        return [
            self._snapshot_from_agent_option(
                option,
                option_id=old_ids.get(option.label, uuid7().hex),
            )
            for option in agent.selectable_model_options
        ]

    @staticmethod
    def _snapshot_from_agent_option(
        option: SelectableModelOption,
        *,
        option_id: str,
    ) -> dict[str, object]:
        return {
            "option_id": option_id,
            "target_label": option.label,
            "label": option.label,
            "model_display_name": option.model_selection.model_display_name,
            "reasoning_efforts": [
                value.value
                for value in (
                    option.model_selection.normalized_capabilities.reasoning.effort_levels
                )
            ],
            "execution_options": [
                definition.model_dump(mode="json")
                for definition in list_model_execution_option_definitions(
                    provider=option.model_selection.provider,
                    supported=option.model_selection.supported_execution_options,
                )
            ],
        }

    def _editor(
        self,
        draft: RDBExternalModelDraft,
        session: AgentSession,
        *,
        offset: int,
        limit: int,
    ) -> ExternalModelEditor:
        options = [self._public_option(value) for value in draft.options_snapshot]
        selected = next(
            option for option in options if option.option_id == draft.selected_option_id
        )
        return ExternalModelEditor(
            draft=ExternalModelDraft(
                id=draft.id,
                owner_interaction_key=draft.owner_interaction_key,
                target=self._draft_target(draft),
                expected_generation=draft.expected_generation,
                selection=ExternalModelDraftSelection(
                    option_id=draft.selected_option_id,
                    reasoning_effort=draft.selected_reasoning_effort,
                    enabled_execution_options=_EXECUTION_OPTION_IDS.validate_python(
                        draft.selected_enabled_execution_options
                    ),
                ),
                selection_fingerprint=self._selection_fingerprint(draft),
                expires_at=draft.expires_at,
            ),
            scope_label=draft.scope_label,
            current_profile=self._requested_profile(session.applied_inference_profile),
            current_generation=session.applied_profile_generation,
            selected_option=selected,
            options=ExternalModelOptionPage(
                items=options[offset : offset + limit],
                offset=offset,
                limit=limit,
                total_count=len(options),
            ),
        )

    @staticmethod
    def _public_option(value: dict[str, object]) -> ExternalModelOption:
        return ExternalModelOption(
            option_id=ExternalModelSettingsRepository._option_id(value),
            label=ExternalModelSettingsRepository._required_string(value, "label"),
            model_display_name=ExternalModelSettingsRepository._required_string(
                value,
                "model_display_name",
            ),
            reasoning_efforts=TypeAdapter(list[str]).validate_python(
                value.get("reasoning_efforts")
            ),
            execution_options=TypeAdapter(
                list[ModelExecutionOptionDefinition]
            ).validate_python(value.get("execution_options")),
        )

    @staticmethod
    def _requested_profile(
        profile: SessionAppliedInferenceProfile | None,
    ) -> RequestedInferenceProfile | None:
        if profile is None:
            return None
        return RequestedInferenceProfile(
            model_target_label=profile.model_target_label,
            reasoning_effort=profile.reasoning_effort,
            enabled_execution_options=profile.enabled_execution_options,
        )

    @staticmethod
    def _draft_target(draft: RDBExternalModelDraft) -> ExternalModelTargetContext:
        return ExternalModelTargetContext(
            binding_id=draft.binding_id,
            session_id=draft.session_id,
            agent_id=draft.agent_id,
        )

    @staticmethod
    def _selection_fingerprint(draft: RDBExternalModelDraft) -> str:
        payload = json.dumps(
            {
                "expected_generation": draft.expected_generation,
                "option_id": draft.selected_option_id,
                "reasoning_effort": (
                    None
                    if draft.selected_reasoning_effort is None
                    else draft.selected_reasoning_effort.value
                ),
                "enabled_execution_options": sorted(
                    draft.selected_enabled_execution_options
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    async def _lock_draft(
        self,
        session: AsyncSession,
        *,
        draft_id: str,
    ) -> RDBExternalModelDraft | None:
        return await session.scalar(
            sa.select(RDBExternalModelDraft)
            .where(RDBExternalModelDraft.id == draft_id)
            .with_for_update(nowait=True)
        )

    @staticmethod
    def _validate_draft(
        draft: RDBExternalModelDraft,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
        now: datetime.datetime,
        allow_applied: bool,
    ) -> ExternalModelRejected | None:
        if not ExternalModelSettingsRepository._actor_matches(draft, actor):
            return ExternalModelRejected(
                code=ExternalModelSettingsRejectionCode.ACTOR_MISMATCH
            )
        if (
            draft.binding_id != target.binding_id
            or draft.session_id != target.session_id
            or draft.agent_id != target.agent_id
        ):
            return ExternalModelRejected(
                code=ExternalModelSettingsRejectionCode.ACTOR_MISMATCH
            )
        if draft.expires_at <= now:
            return ExternalModelRejected(
                code=ExternalModelSettingsRejectionCode.DRAFT_EXPIRED
            )
        if draft.cancelled_at is not None or (
            draft.applied_at is not None and not allow_applied
        ):
            return ExternalModelRejected(
                code=ExternalModelSettingsRejectionCode.DRAFT_NOT_FOUND
            )
        return None

    @staticmethod
    def _actor_matches(
        draft: RDBExternalModelDraft,
        actor: ExternalModelActorContext,
    ) -> bool:
        return (
            draft.provider is actor.provider
            and draft.connection_id == actor.connection_id
            and draft.principal_id == actor.principal_id
        )

    @staticmethod
    def _mutation_matches(
        mutation: RDBExternalModelMutation,
        *,
        actor: ExternalModelActorContext,
        target: ExternalModelTargetContext,
        user_id: str,
    ) -> bool:
        return (
            mutation.provider is actor.provider
            and mutation.connection_id == actor.connection_id
            and mutation.principal_id_snapshot == actor.principal_id
            and mutation.provider_tenant_id_snapshot == actor.provider_tenant_id
            and mutation.provider_user_id_snapshot == actor.provider_user_id
            and mutation.binding_id_snapshot == target.binding_id
            and mutation.session_id == target.session_id
            and mutation.agent_id_snapshot == target.agent_id
            and mutation.user_id_snapshot == user_id
        )

    @staticmethod
    def _scope_label(resource: RDBExternalChannelResource) -> str:
        labels = resource.labels or {}
        for key in ("thread_label", "channel_name", "display_name", "channel_id"):
            value = labels.get(key)
            if isinstance(value, str) and value:
                return value[:255]
        return resource.provider_resource_key[:255]

    @staticmethod
    def _notice_target(
        authorized: _AuthorizedModelTarget,
    ) -> _ExternalModelNoticeTarget:
        labels = authorized.resource.labels or {}
        if authorized.connection.provider is ExternalChannelProvider.SLACK:
            channel_id = labels.get("channel_id")
            thread_id = labels.get("thread_ts")
            if not isinstance(channel_id, str) or not channel_id:
                raise ValueError("Slack notice target is unavailable")
            return _ExternalModelNoticeTarget(
                provider_conversation_id=channel_id,
                provider_thread_id=thread_id if isinstance(thread_id, str) else None,
            )
        guild_id = labels.get("guild_id")
        scope = labels.get("conversation_scope")
        channel_id = (
            labels.get("parent_channel_id")
            if scope == "parent_channel"
            else labels.get("delivery_channel_id") or labels.get("thread_id")
        )
        if (
            not isinstance(guild_id, str)
            or not guild_id
            or not isinstance(channel_id, str)
            or not channel_id
        ):
            raise ValueError("Discord notice target is unavailable")
        return _ExternalModelNoticeTarget(
            provider_conversation_id=guild_id, provider_thread_id=channel_id
        )

    @staticmethod
    def _notice_plan(mutation: RDBExternalModelMutation) -> ExternalModelNoticePlan:
        return ExternalModelNoticePlan(
            mutation_id=mutation.id,
            provider=mutation.provider,
            connection_id=mutation.connection_id,
            provider_conversation_id=mutation.provider_conversation_id,
            provider_thread_id=mutation.provider_thread_id,
            actor_display_name=mutation.actor_display_name_snapshot,
            model_label=mutation.new_model_target_label,
            model_display_name=mutation.new_model_display_name,
            reasoning_effort=mutation.new_reasoning_effort,
            enabled_execution_option_labels=[
                MODEL_EXECUTION_OPTION_DEFINITIONS[value].label
                for value in _EXECUTION_OPTION_IDS.validate_python(
                    mutation.new_enabled_execution_options
                )
            ],
        )

    @staticmethod
    def _snapshot_option(
        draft: RDBExternalModelDraft,
        option_id: str,
    ) -> dict[str, object] | None:
        return next(
            (
                option
                for option in draft.options_snapshot
                if ExternalModelSettingsRepository._option_id(option) == option_id
            ),
            None,
        )

    @staticmethod
    def _option_for_target(
        options: list[dict[str, object]],
        target_label: str,
    ) -> dict[str, object] | None:
        return next(
            (
                option
                for option in options
                if ExternalModelSettingsRepository._option_target_label(option)
                == target_label
            ),
            None,
        )

    @staticmethod
    def _option_id(option: dict[str, object]) -> str:
        return ExternalModelSettingsRepository._required_string(option, "option_id")

    @staticmethod
    def _option_target_label(option: dict[str, object]) -> str:
        return ExternalModelSettingsRepository._required_string(option, "target_label")

    @staticmethod
    def _required_string(value: dict[str, object], key: str) -> str:
        result = value.get(key)
        if not isinstance(result, str) or not result:
            raise RuntimeError("External model draft option snapshot is invalid")
        return result

    @staticmethod
    def _require_authorized(
        result: _AuthorizationResult,
    ) -> _AuthorizedModelTarget:
        if result.target is None or result.rejection is not None:
            raise RuntimeError("External model authorization result is incomplete")
        return result.target

    @staticmethod
    def _rejected(code: ExternalModelSettingsRejectionCode) -> _AuthorizationResult:
        return _AuthorizationResult(
            target=None,
            rejection=ExternalModelRejected(code=code),
        )

    @staticmethod
    def _validate_page(*, offset: int, limit: int) -> None:
        if offset < 0 or limit < 1 or limit > 25:
            raise ValueError("External model option page is invalid")

    @staticmethod
    def _retryable(error: DBAPIError) -> bool:
        current: object | None = error
        while current is not None:
            sqlstate = getattr(current, "sqlstate", None)
            if isinstance(sqlstate, str) and sqlstate in _RETRYABLE_SQLSTATES:
                return True
            current = getattr(current, "orig", None)
        return False

    @staticmethod
    def _lock_not_available() -> DBAPIError:
        return DBAPIError(
            statement=None,
            params=None,
            orig=_RetryableLockConflict(),
            connection_invalidated=False,
        )


class _RetryableLockConflict(Exception):
    """Synthetic advisory-fence conflict classified like PostgreSQL NOWAIT."""

    sqlstate = "55P03"
