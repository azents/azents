"""Completed database operations for external account linking."""

import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated, TypeVar
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
)
from azents.core.external_account_link import (
    EXTERNAL_ACCOUNT_LINK_MAX_CANDIDATES,
    EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES,
    EXTERNAL_ACCOUNT_LINK_ORIGIN_TTL,
    ExternalAccountLinkActorMismatch,
    ExternalAccountLinkAttemptLimitReached,
    ExternalAccountLinkBusy,
    ExternalAccountLinkCandidateCreated,
    ExternalAccountLinkCandidateNotReady,
    ExternalAccountLinkCandidateStatus,
    ExternalAccountLinkCandidateTerminal,
    ExternalAccountLinkCandidateView,
    ExternalAccountLinkCleanupSummary,
    ExternalAccountLinkConflict,
    ExternalAccountLinkExpired,
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkMembershipRequired,
    ExternalAccountLinkNotFound,
    ExternalAccountLinkOriginState,
    ExternalAccountLinkOriginView,
    ExternalAccountLinkReturnContext,
    ExternalAccountLinkReturnKind,
    ExternalAccountLinkState,
    ExternalAccountLinkUnavailable,
    ExternalAccountLinkView,
    ExternalAccountNativeLinkState,
    ExternalAccountOriginCreated,
    ExternalAccountProviderProofResult,
    VerifiedExternalAccountActor,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.external_account_link import (
    RDBExternalAccountLink,
    RDBExternalAccountLinkCandidate,
    RDBExternalAccountLinkOrigin,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelConnection,
    RDBExternalChannelPrincipal,
)
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager

from .data import ExternalAccountLink

_T = TypeVar("_T")
_RETRYABLE_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
_MAX_TRANSACTION_ATTEMPTS = 3
_LOCK_TIMEOUT = "2s"
_MANAGEMENT_PATH = "/account/external-accounts"


class ExternalAccountLinkRepository:
    """Own external account link transactions and lifecycle locks."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession],
            Depends(get_session_manager),
        ],
    ) -> None:
        self.session_manager = session_manager

    async def lock_active_link(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        provider: ExternalChannelProvider,
        identity_scope: str,
        provider_user_id: str,
        nowait: bool = True,
    ) -> ExternalAccountLink | None:
        """Lock the actual active link row for repository composition."""
        rdb = await session.scalar(
            sa.select(RDBExternalAccountLink)
            .where(
                RDBExternalAccountLink.workspace_id == workspace_id,
                RDBExternalAccountLink.provider == provider,
                RDBExternalAccountLink.identity_scope == identity_scope,
                RDBExternalAccountLink.provider_user_id == provider_user_id,
                RDBExternalAccountLink.revoked_at.is_(None),
            )
            .with_for_update(nowait=nowait)
        )
        return None if rdb is None else _link_record(rdb)

    async def get_native_link_state(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        now: datetime.datetime,
    ) -> ExternalAccountNativeLinkState:
        """Resolve actor-private link state in one completed transaction."""
        async with self.session_manager() as session:
            workspace_id, identity_scope = await self._validate_actor(
                session,
                actor=actor,
                lock=False,
            )
            link = await session.scalar(
                sa.select(RDBExternalAccountLink).where(
                    RDBExternalAccountLink.workspace_id == workspace_id,
                    RDBExternalAccountLink.provider == actor.provider,
                    RDBExternalAccountLink.identity_scope == identity_scope,
                    RDBExternalAccountLink.provider_user_id == actor.provider_user_id,
                    RDBExternalAccountLink.revoked_at.is_(None),
                )
            )
            if link is None:
                return ExternalAccountNativeLinkState(
                    link=None,
                    management_path=_MANAGEMENT_PATH,
                )
            return ExternalAccountNativeLinkState(
                link=await self._build_link_view(session, link),
                management_path=_MANAGEMENT_PATH,
            )

    async def create_origin(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        now: datetime.datetime,
    ) -> ExternalAccountOriginCreated:
        """Create or replay one actor-bound provider origin."""

        async def operation(session: AsyncSession) -> ExternalAccountOriginCreated:
            workspace_id, identity_scope = await self._validate_actor(
                session,
                actor=actor,
                lock=True,
            )
            existing = await session.scalar(
                sa.select(RDBExternalAccountLinkOrigin)
                .where(
                    RDBExternalAccountLinkOrigin.connection_id == actor.connection_id,
                    RDBExternalAccountLinkOrigin.provider_interaction_id
                    == actor.provider_interaction_id,
                )
                .with_for_update(nowait=True)
            )
            if existing is not None:
                self._require_matching_origin(existing, actor)
                if (
                    _origin_state(existing, now)
                    is not ExternalAccountLinkOriginState.OPEN
                ):
                    raise ExternalAccountLinkConflict
                return _origin_created(existing)

            origin = RDBExternalAccountLinkOrigin(
                workspace_id=workspace_id,
                connection_id=actor.connection_id,
                connection_configuration_generation=(
                    actor.connection_configuration_generation
                ),
                principal_id=actor.principal_id,
                provider=actor.provider,
                identity_scope=identity_scope,
                provider_tenant_id=actor.provider_tenant_id,
                provider_tenant_display_label=_safe_tenant_label(actor),
                provider_user_id=actor.provider_user_id,
                provider_display_label=_safe_actor_label(actor),
                provider_interaction_id=actor.provider_interaction_id,
                provider_channel_id=actor.provider_channel_id,
                provider_thread_id=actor.provider_thread_id,
                expires_at=now + EXTERNAL_ACCOUNT_LINK_ORIGIN_TTL,
                candidate_count=0,
                invalid_code_count=0,
                cancelled_at=None,
                consumed_at=None,
            )
            session.add(origin)
            await session.flush()
            return _origin_created(origin)

        return await self._run_retryable(operation)

    async def verify_candidate_code(
        self,
        *,
        actor: VerifiedExternalAccountActor,
        origin_id: str,
        code_hash: str,
        now: datetime.datetime,
    ) -> ExternalAccountProviderProofResult:
        """Verify one code only after original actor scope validation."""
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            invalid_code: ExternalAccountLinkInvalidCode | None = None
            try:
                async with self.session_manager() as session:
                    await _set_lock_timeout(session)
                    await self._validate_actor(session, actor=actor, lock=True)
                    origin = await session.scalar(
                        sa.select(RDBExternalAccountLinkOrigin)
                        .where(RDBExternalAccountLinkOrigin.id == origin_id)
                        .with_for_update(nowait=True)
                    )
                    if origin is None:
                        raise ExternalAccountLinkNotFound
                    self._require_matching_origin(origin, actor)
                    self._require_open_origin(origin, now)
                    if (
                        origin.invalid_code_count
                        >= EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES
                    ):
                        raise ExternalAccountLinkAttemptLimitReached

                    candidate = await session.scalar(
                        sa.select(RDBExternalAccountLinkCandidate)
                        .where(
                            RDBExternalAccountLinkCandidate.origin_id == origin.id,
                            RDBExternalAccountLinkCandidate.code_hash == code_hash,
                        )
                        .with_for_update(nowait=True)
                    )
                    if candidate is None:
                        origin.invalid_code_count += 1
                        remaining = (
                            EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES
                            - origin.invalid_code_count
                        )
                        await session.flush()
                        invalid_code = ExternalAccountLinkInvalidCode(
                            remaining_attempts=remaining
                        )
                    else:
                        status = _candidate_status(candidate, now)
                        if status is ExternalAccountLinkCandidateStatus.EXPIRED:
                            raise ExternalAccountLinkExpired
                        if status in (
                            ExternalAccountLinkCandidateStatus.CANCELLED,
                            ExternalAccountLinkCandidateStatus.CONNECTED,
                        ):
                            raise ExternalAccountLinkCandidateTerminal
                        if candidate.provider_proved_at is None:
                            candidate.provider_proved_at = now
                            await session.flush()
                        result = ExternalAccountProviderProofResult(
                            candidate_id=candidate.id,
                            status=ExternalAccountLinkCandidateStatus.PROVIDER_VERIFIED,
                            remaining_attempts=(
                                EXTERNAL_ACCOUNT_LINK_MAX_INVALID_CODES
                                - origin.invalid_code_count
                            ),
                        )
                if invalid_code is not None:
                    raise invalid_code
                return result
            except IntegrityError as error:
                raise ExternalAccountLinkConflict from error
            except DBAPIError as error:
                if _is_retryable(error) and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS:
                    continue
                if _is_retryable(error):
                    raise ExternalAccountLinkBusy from error
                raise
        raise ExternalAccountLinkBusy

    async def list_links(
        self,
        *,
        user_id: str,
        now: datetime.datetime,
    ) -> list[ExternalAccountLinkView]:
        """List the current User's Workspace links."""
        del now
        async with self.session_manager() as session:
            rows = (
                await session.execute(
                    sa.select(
                        RDBExternalAccountLink,
                        RDBWorkspace,
                        RDBWorkspaceUser.id,
                        RDBUser.access_disabled_at,
                    )
                    .join(
                        RDBWorkspace,
                        RDBWorkspace.id == RDBExternalAccountLink.workspace_id,
                    )
                    .join(RDBUser, RDBUser.id == RDBExternalAccountLink.user_id)
                    .outerjoin(
                        RDBWorkspaceUser,
                        sa.and_(
                            RDBWorkspaceUser.workspace_id
                            == RDBExternalAccountLink.workspace_id,
                            RDBWorkspaceUser.user_id == RDBExternalAccountLink.user_id,
                        ),
                    )
                    .where(RDBExternalAccountLink.user_id == user_id)
                    .order_by(
                        RDBExternalAccountLink.linked_at.desc(),
                        RDBExternalAccountLink.id,
                    )
                )
            ).all()
            return [
                _link_view(
                    link,
                    workspace,
                    ExternalAccountLinkState.REVOKED
                    if link.revoked_at is not None
                    else ExternalAccountLinkState.ACTIVE
                    if membership_id is not None and access_disabled_at is None
                    else ExternalAccountLinkState.INACTIVE,
                )
                for link, workspace, membership_id, access_disabled_at in rows
            ]

    async def unlink(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        link_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkView:
        """Terminally revoke an owned link."""

        async def operation(session: AsyncSession) -> ExternalAccountLinkView:
            await self._lock_active_user_session(
                session,
                user_id=user_id,
                auth_session_id=auth_session_id,
                now=now,
            )
            link = await session.scalar(
                sa.select(RDBExternalAccountLink)
                .where(
                    RDBExternalAccountLink.id == link_id,
                    RDBExternalAccountLink.user_id == user_id,
                )
                .with_for_update(nowait=True)
            )
            if link is None:
                raise ExternalAccountLinkNotFound
            if link.revoked_at is None:
                link.revoked_at = now
                await session.flush()
            return await self._build_link_view(session, link)

        return await self._run_retryable(operation)

    async def get_origin(
        self,
        *,
        user_id: str,
        origin_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkOriginView:
        """Get browser-safe origin context."""
        async with self.session_manager() as session:
            user = await session.get(RDBUser, user_id)
            if user is None or user.access_disabled_at is not None:
                raise ExternalAccountLinkUnavailable
            row = (
                await session.execute(
                    sa.select(RDBExternalAccountLinkOrigin, RDBWorkspace)
                    .join(
                        RDBWorkspace,
                        RDBWorkspace.id == RDBExternalAccountLinkOrigin.workspace_id,
                    )
                    .where(RDBExternalAccountLinkOrigin.id == origin_id)
                )
            ).one_or_none()
            if row is None:
                raise ExternalAccountLinkNotFound
            origin, workspace = row
            return _origin_view(origin, workspace, now)

    async def create_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        origin_id: str,
        code_hash: str,
        plaintext_code: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateCreated:
        """Create one immutable candidate after live authority validation."""

        async def operation(
            session: AsyncSession,
        ) -> ExternalAccountLinkCandidateCreated:
            origin = await session.scalar(
                sa.select(RDBExternalAccountLinkOrigin)
                .where(RDBExternalAccountLinkOrigin.id == origin_id)
                .with_for_update(nowait=True)
            )
            if origin is None:
                raise ExternalAccountLinkNotFound
            self._require_open_origin(origin, now)
            await self._lock_active_user_session(
                session,
                user_id=user_id,
                auth_session_id=auth_session_id,
                now=now,
            )
            await self._lock_membership(
                session,
                workspace_id=origin.workspace_id,
                user_id=user_id,
            )
            await self._lock_current_origin_connection(session, origin)
            if origin.candidate_count >= EXTERNAL_ACCOUNT_LINK_MAX_CANDIDATES:
                raise ExternalAccountLinkConflict
            origin.candidate_count += 1
            candidate = RDBExternalAccountLinkCandidate(
                origin_id=origin.id,
                user_id=user_id,
                auth_session_id=auth_session_id,
                code_hash=code_hash,
                expires_at=origin.expires_at,
                provider_proved_at=None,
                cancelled_at=None,
                consumed_at=None,
                link_id=None,
            )
            session.add(candidate)
            await session.flush()
            return ExternalAccountLinkCandidateCreated(
                id=candidate.id,
                origin_id=candidate.origin_id,
                code=plaintext_code,
                expires_at=candidate.expires_at,
                status=ExternalAccountLinkCandidateStatus.PENDING_PROVIDER_PROOF,
            )

        return await self._run_retryable(operation)

    async def get_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateView:
        """Get exact candidate owner/auth-Session status."""
        async with self.session_manager() as session:
            candidate = await session.scalar(
                sa.select(RDBExternalAccountLinkCandidate).where(
                    RDBExternalAccountLinkCandidate.id == candidate_id,
                    RDBExternalAccountLinkCandidate.user_id == user_id,
                    RDBExternalAccountLinkCandidate.auth_session_id == auth_session_id,
                )
            )
            if candidate is None:
                raise ExternalAccountLinkNotFound
            return _candidate_view(candidate, now)

    async def confirm_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkView:
        """Atomically finalize a provider-proved candidate."""

        async def operation(session: AsyncSession) -> ExternalAccountLinkView:
            candidate = await session.scalar(
                sa.select(RDBExternalAccountLinkCandidate)
                .where(
                    RDBExternalAccountLinkCandidate.id == candidate_id,
                    RDBExternalAccountLinkCandidate.user_id == user_id,
                    RDBExternalAccountLinkCandidate.auth_session_id == auth_session_id,
                )
                .with_for_update(nowait=True)
            )
            if candidate is None:
                raise ExternalAccountLinkNotFound
            await self._lock_active_user_session(
                session,
                user_id=user_id,
                auth_session_id=auth_session_id,
                now=now,
            )
            if candidate.consumed_at is not None and candidate.link_id is not None:
                replay_link = await session.get(
                    RDBExternalAccountLink,
                    candidate.link_id,
                    with_for_update={"nowait": True},
                )
                if replay_link is None or replay_link.user_id != user_id:
                    raise ExternalAccountLinkNotFound
                return await self._build_link_view(session, replay_link)

            status = _candidate_status(candidate, now)
            if status is ExternalAccountLinkCandidateStatus.EXPIRED:
                raise ExternalAccountLinkExpired
            if status is ExternalAccountLinkCandidateStatus.CANCELLED:
                raise ExternalAccountLinkCandidateTerminal
            if status is not ExternalAccountLinkCandidateStatus.PROVIDER_VERIFIED:
                raise ExternalAccountLinkCandidateNotReady

            origin = await session.scalar(
                sa.select(RDBExternalAccountLinkOrigin)
                .where(RDBExternalAccountLinkOrigin.id == candidate.origin_id)
                .with_for_update(nowait=True)
            )
            if origin is None:
                raise ExternalAccountLinkNotFound
            self._require_open_origin(origin, now)
            await self._lock_membership(
                session,
                workspace_id=origin.workspace_id,
                user_id=user_id,
            )
            await self._lock_current_origin_connection(session, origin)

            active_links = (
                await session.scalars(
                    sa.select(RDBExternalAccountLink)
                    .where(
                        RDBExternalAccountLink.workspace_id == origin.workspace_id,
                        RDBExternalAccountLink.provider == origin.provider,
                        RDBExternalAccountLink.identity_scope == origin.identity_scope,
                        RDBExternalAccountLink.revoked_at.is_(None),
                        sa.or_(
                            RDBExternalAccountLink.provider_user_id
                            == origin.provider_user_id,
                            RDBExternalAccountLink.user_id == user_id,
                        ),
                    )
                    .with_for_update(nowait=True)
                )
            ).all()
            exact_link = next(
                (
                    link
                    for link in active_links
                    if link.user_id == user_id
                    and link.provider_user_id == origin.provider_user_id
                ),
                None,
            )
            if exact_link is None and active_links:
                raise ExternalAccountLinkConflict
            if exact_link is None:
                exact_link = RDBExternalAccountLink(
                    workspace_id=origin.workspace_id,
                    user_id=user_id,
                    provider=origin.provider,
                    identity_scope=origin.identity_scope,
                    provider_user_id=origin.provider_user_id,
                    provider_tenant_display_label=(
                        origin.provider_tenant_display_label
                    ),
                    provider_display_label=origin.provider_display_label,
                    linked_at=now,
                    revoked_at=None,
                )
                session.add(exact_link)
                await session.flush()
            else:
                exact_link.provider_tenant_display_label = (
                    origin.provider_tenant_display_label
                )
                exact_link.provider_display_label = origin.provider_display_label

            origin.consumed_at = now
            candidate.consumed_at = now
            candidate.link_id = exact_link.id
            await session.execute(
                sa.update(RDBExternalAccountLinkCandidate)
                .where(
                    RDBExternalAccountLinkCandidate.origin_id == origin.id,
                    RDBExternalAccountLinkCandidate.id != candidate.id,
                    RDBExternalAccountLinkCandidate.consumed_at.is_(None),
                    RDBExternalAccountLinkCandidate.cancelled_at.is_(None),
                )
                .values(cancelled_at=now)
            )
            await session.flush()
            return await self._build_link_view(session, exact_link)

        return await self._run_retryable(operation)

    async def cancel_candidate(
        self,
        *,
        user_id: str,
        auth_session_id: str,
        candidate_id: str,
        now: datetime.datetime,
    ) -> ExternalAccountLinkCandidateView:
        """Cancel an exact owned candidate."""

        async def operation(session: AsyncSession) -> ExternalAccountLinkCandidateView:
            candidate = await session.scalar(
                sa.select(RDBExternalAccountLinkCandidate)
                .where(
                    RDBExternalAccountLinkCandidate.id == candidate_id,
                    RDBExternalAccountLinkCandidate.user_id == user_id,
                    RDBExternalAccountLinkCandidate.auth_session_id == auth_session_id,
                )
                .with_for_update(nowait=True)
            )
            if candidate is None:
                raise ExternalAccountLinkNotFound
            if candidate.expires_at <= now:
                raise ExternalAccountLinkExpired
            if candidate.consumed_at is None and candidate.cancelled_at is None:
                candidate.cancelled_at = now
                await session.flush()
            return _candidate_view(candidate, now)

        return await self._run_retryable(operation)

    async def cleanup_expired(
        self,
        *,
        cutoff: datetime.datetime,
        limit: int,
    ) -> ExternalAccountLinkCleanupSummary:
        """Delete one bounded batch of stale proof rows."""
        if limit <= 0:
            return ExternalAccountLinkCleanupSummary(
                deleted_origin_count=0,
                deleted_candidate_count=0,
            )
        async with self.session_manager() as session:
            origin_ids = (
                await session.scalars(
                    sa.select(RDBExternalAccountLinkOrigin.id)
                    .where(RDBExternalAccountLinkOrigin.expires_at <= cutoff)
                    .order_by(
                        RDBExternalAccountLinkOrigin.expires_at,
                        RDBExternalAccountLinkOrigin.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(limit)
                )
            ).all()
            if not origin_ids:
                return ExternalAccountLinkCleanupSummary(
                    deleted_origin_count=0,
                    deleted_candidate_count=0,
                )
            candidate_count = await session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalAccountLinkCandidate)
                .where(RDBExternalAccountLinkCandidate.origin_id.in_(origin_ids))
            )
            await session.execute(
                sa.delete(RDBExternalAccountLinkOrigin).where(
                    RDBExternalAccountLinkOrigin.id.in_(origin_ids)
                )
            )
            return ExternalAccountLinkCleanupSummary(
                deleted_origin_count=len(origin_ids),
                deleted_candidate_count=candidate_count or 0,
            )

    async def _run_retryable(
        self,
        operation: Callable[[AsyncSession], Awaitable[_T]],
    ) -> _T:
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session_manager() as session:
                    await _set_lock_timeout(session)
                    return await operation(session)
            except IntegrityError as error:
                if _sqlstate(error) == "23505":
                    raise ExternalAccountLinkConflict from error
                raise
            except DBAPIError as error:
                if _is_retryable(error) and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS:
                    continue
                if _is_retryable(error):
                    raise ExternalAccountLinkBusy from error
                raise
        raise ExternalAccountLinkBusy

    async def _validate_actor(
        self,
        session: AsyncSession,
        *,
        actor: VerifiedExternalAccountActor,
        lock: bool,
    ) -> tuple[str, str]:
        connection_query = sa.select(RDBExternalChannelConnection).where(
            RDBExternalChannelConnection.id == actor.connection_id
        )
        principal_query = sa.select(RDBExternalChannelPrincipal).where(
            RDBExternalChannelPrincipal.id == actor.principal_id
        )
        if lock:
            connection_query = connection_query.with_for_update(nowait=True)
            principal_query = principal_query.with_for_update(nowait=True)
        connection = await session.scalar(connection_query)
        principal = await session.scalar(principal_query)
        if (
            connection is None
            or principal is None
            or connection.provider != actor.provider
            or connection.provider_tenant_id != actor.provider_tenant_id
            or connection.configuration_generation
            != actor.connection_configuration_generation
            or connection.status
            not in (
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            )
            or principal.provider != actor.provider
            or principal.provider_tenant_id != actor.provider_tenant_id
            or principal.provider_user_id != actor.provider_user_id
            or principal.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            raise ExternalAccountLinkActorMismatch
        return connection.workspace_id, _identity_scope(actor)

    async def _lock_active_user_session(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        auth_session_id: str,
        now: datetime.datetime,
    ) -> None:
        user = await session.scalar(
            sa.select(RDBUser).where(RDBUser.id == user_id).with_for_update(nowait=True)
        )
        auth_session = await session.scalar(
            sa.select(RDBSession)
            .where(
                RDBSession.id == auth_session_id,
                RDBSession.user_id == user_id,
            )
            .with_for_update(nowait=True)
        )
        if (
            user is None
            or user.access_disabled_at is not None
            or auth_session is None
            or auth_session.revoked_at is not None
            or auth_session.expires_at <= now
        ):
            raise ExternalAccountLinkUnavailable

    async def _lock_membership(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> None:
        membership_id = await session.scalar(
            sa.select(RDBWorkspaceUser.id)
            .where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user_id,
            )
            .with_for_update(nowait=True)
        )
        if membership_id is None:
            raise ExternalAccountLinkMembershipRequired

    async def _lock_current_origin_connection(
        self,
        session: AsyncSession,
        origin: RDBExternalAccountLinkOrigin,
    ) -> None:
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == origin.connection_id)
            .with_for_update(nowait=True)
        )
        if (
            connection is None
            or connection.workspace_id != origin.workspace_id
            or connection.provider != origin.provider
            or connection.provider_tenant_id != origin.provider_tenant_id
            or connection.configuration_generation
            != origin.connection_configuration_generation
            or connection.status
            not in (
                ExternalChannelConnectionStatus.ACTIVE,
                ExternalChannelConnectionStatus.DEGRADED,
            )
        ):
            raise ExternalAccountLinkUnavailable

    async def _build_link_view(
        self,
        session: AsyncSession,
        link: RDBExternalAccountLink,
    ) -> ExternalAccountLinkView:
        workspace = await session.get(RDBWorkspace, link.workspace_id)
        if workspace is None:
            raise ExternalAccountLinkNotFound
        user = await session.get(RDBUser, link.user_id)
        membership_id = await session.scalar(
            sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == link.workspace_id,
                RDBWorkspaceUser.user_id == link.user_id,
            )
        )
        state = (
            ExternalAccountLinkState.REVOKED
            if link.revoked_at is not None
            else ExternalAccountLinkState.ACTIVE
            if membership_id is not None
            and user is not None
            and user.access_disabled_at is None
            else ExternalAccountLinkState.INACTIVE
        )
        return _link_view(link, workspace, state)

    @staticmethod
    def _require_matching_origin(
        origin: RDBExternalAccountLinkOrigin,
        actor: VerifiedExternalAccountActor,
    ) -> None:
        if (
            origin.connection_id != actor.connection_id
            or origin.connection_configuration_generation
            != actor.connection_configuration_generation
            or origin.principal_id != actor.principal_id
            or origin.provider != actor.provider
            or origin.provider_tenant_id != actor.provider_tenant_id
            or origin.provider_user_id != actor.provider_user_id
        ):
            raise ExternalAccountLinkActorMismatch

    @staticmethod
    def _require_open_origin(
        origin: RDBExternalAccountLinkOrigin,
        now: datetime.datetime,
    ) -> None:
        state = _origin_state(origin, now)
        if state is ExternalAccountLinkOriginState.EXPIRED:
            raise ExternalAccountLinkExpired
        if state is not ExternalAccountLinkOriginState.OPEN:
            raise ExternalAccountLinkCandidateTerminal


def _link_record(rdb: RDBExternalAccountLink) -> ExternalAccountLink:
    return ExternalAccountLink(
        id=rdb.id,
        workspace_id=rdb.workspace_id,
        user_id=rdb.user_id,
        provider=rdb.provider,
        identity_scope=rdb.identity_scope,
        provider_user_id=rdb.provider_user_id,
        provider_tenant_display_label=rdb.provider_tenant_display_label,
        provider_display_label=rdb.provider_display_label,
        linked_at=rdb.linked_at,
        revoked_at=rdb.revoked_at,
    )


def _link_view(
    link: RDBExternalAccountLink,
    workspace: RDBWorkspace,
    state: ExternalAccountLinkState,
) -> ExternalAccountLinkView:
    return ExternalAccountLinkView(
        id=link.id,
        workspace_id=link.workspace_id,
        workspace_name=workspace.name,
        workspace_handle=workspace.handle,
        user_id=link.user_id,
        provider=link.provider,
        identity_scope=link.identity_scope,
        provider_user_id=link.provider_user_id,
        provider_tenant_display_label=link.provider_tenant_display_label,
        provider_display_label=link.provider_display_label,
        linked_at=link.linked_at,
        state=state,
    )


def _origin_created(
    origin: RDBExternalAccountLinkOrigin,
) -> ExternalAccountOriginCreated:
    return ExternalAccountOriginCreated(
        origin_id=origin.id,
        expires_at=origin.expires_at,
        web_path=f"/external-channel/link/{origin.id}",
        management_path=_MANAGEMENT_PATH,
    )


def _origin_view(
    origin: RDBExternalAccountLinkOrigin,
    workspace: RDBWorkspace,
    now: datetime.datetime,
) -> ExternalAccountLinkOriginView:
    return ExternalAccountLinkOriginView(
        id=origin.id,
        workspace_id=origin.workspace_id,
        workspace_name=workspace.name,
        workspace_handle=workspace.handle,
        provider=origin.provider,
        identity_scope=origin.identity_scope,
        provider_tenant_id=origin.provider_tenant_id,
        provider_tenant_display_label=origin.provider_tenant_display_label,
        provider_display_label=origin.provider_display_label,
        expires_at=origin.expires_at,
        state=_origin_state(origin, now),
        candidate_count=origin.candidate_count,
        invalid_code_count=origin.invalid_code_count,
        return_context=ExternalAccountLinkReturnContext(
            kind=_return_kind(origin.provider),
            provider_tenant_display_label=origin.provider_tenant_display_label,
            provider_url=_provider_return_url(origin),
        ),
    )


def _candidate_view(
    candidate: RDBExternalAccountLinkCandidate,
    now: datetime.datetime,
) -> ExternalAccountLinkCandidateView:
    return ExternalAccountLinkCandidateView(
        id=candidate.id,
        origin_id=candidate.origin_id,
        expires_at=candidate.expires_at,
        status=_candidate_status(candidate, now),
        link_id=candidate.link_id,
    )


def _candidate_status(
    candidate: RDBExternalAccountLinkCandidate,
    now: datetime.datetime,
) -> ExternalAccountLinkCandidateStatus:
    if candidate.consumed_at is not None and candidate.link_id is not None:
        return ExternalAccountLinkCandidateStatus.CONNECTED
    if candidate.cancelled_at is not None:
        return ExternalAccountLinkCandidateStatus.CANCELLED
    if candidate.expires_at <= now:
        return ExternalAccountLinkCandidateStatus.EXPIRED
    if candidate.provider_proved_at is not None:
        return ExternalAccountLinkCandidateStatus.PROVIDER_VERIFIED
    return ExternalAccountLinkCandidateStatus.PENDING_PROVIDER_PROOF


def _origin_state(
    origin: RDBExternalAccountLinkOrigin,
    now: datetime.datetime,
) -> ExternalAccountLinkOriginState:
    if origin.consumed_at is not None:
        return ExternalAccountLinkOriginState.CONSUMED
    if origin.cancelled_at is not None:
        return ExternalAccountLinkOriginState.CANCELLED
    if origin.expires_at <= now:
        return ExternalAccountLinkOriginState.EXPIRED
    return ExternalAccountLinkOriginState.OPEN


def _identity_scope(actor: VerifiedExternalAccountActor) -> str:
    if actor.provider is ExternalChannelProvider.DISCORD:
        return "global"
    return actor.provider_tenant_id


def _safe_tenant_label(actor: VerifiedExternalAccountActor) -> str:
    label = actor.provider_tenant_display_label
    if label is not None and label.strip():
        return label.strip()[:255]
    return actor.provider_tenant_id[:255]


def _safe_actor_label(actor: VerifiedExternalAccountActor) -> str:
    if actor.provider_display_label.strip():
        return actor.provider_display_label.strip()[:255]
    if actor.provider is ExternalChannelProvider.DISCORD:
        return "Discord user"
    return "Slack user"


def _return_kind(provider: ExternalChannelProvider) -> ExternalAccountLinkReturnKind:
    if provider is ExternalChannelProvider.SLACK:
        return ExternalAccountLinkReturnKind.SLACK_CONVERSATION
    return ExternalAccountLinkReturnKind.DISCORD_CONVERSATION


def _provider_return_url(origin: RDBExternalAccountLinkOrigin) -> str | None:
    tenant = quote(origin.provider_tenant_id, safe="")
    if origin.provider is ExternalChannelProvider.SLACK:
        channel = quote(origin.provider_channel_id, safe="")
        return f"https://slack.com/app_redirect?team={tenant}&channel={channel}"
    if origin.provider is ExternalChannelProvider.DISCORD:
        channel = quote(
            origin.provider_thread_id or origin.provider_channel_id,
            safe="",
        )
        return f"https://discord.com/channels/{tenant}/{channel}"
    return None


async def _set_lock_timeout(session: AsyncSession) -> None:
    await session.execute(sa.text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))


def _is_retryable(error: DBAPIError) -> bool:
    return _sqlstate(error) in _RETRYABLE_SQLSTATES


def _sqlstate(error: DBAPIError) -> str | None:
    original = error.orig
    state = getattr(original, "sqlstate", None)
    if isinstance(state, str):
        return state
    cause = getattr(original, "__cause__", None)
    state = getattr(cause, "sqlstate", None)
    return state if isinstance(state, str) else None
