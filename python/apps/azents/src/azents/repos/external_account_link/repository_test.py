"""External account link repository integration tests."""

import dataclasses
import datetime
import hashlib
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
    WorkspaceUserRole,
)
from azents.core.external_account_link import (
    ExternalAccountLinkActorMismatch,
    ExternalAccountLinkCandidateStatus,
    ExternalAccountLinkInvalidCode,
    ExternalAccountLinkState,
    VerifiedExternalAccountActor,
)
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
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate

from . import ExternalAccountLinkRepository


@pytest.fixture(autouse=True)
async def _cleanup_committed_link_test_rows(
    rdb_engine: AsyncEngine,
) -> AsyncGenerator[None]:
    """Remove rows committed through repository-owned test transactions."""
    yield
    await _cleanup_link_test_rows(rdb_engine)


@pytest.mark.asyncio
async def test_link_protocol_reuses_global_link_after_membership_loss(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Complete both proofs without changing guest principal or global reuse."""
    fixture = await _create_fixture(rdb_session_manager)
    repository = ExternalAccountLinkRepository(rdb_session_manager)
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)

    origin = await repository.create_origin(actor=fixture.actor, now=now)
    candidate = await repository.create_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        origin_id=origin.origin_id,
        code_hash=hashlib.sha256(b"browser-code").hexdigest(),
        plaintext_code="browser-code",
        now=now,
    )
    assert candidate.status is ExternalAccountLinkCandidateStatus.PENDING_PROVIDER_PROOF

    mismatched_actor = dataclasses.replace(
        fixture.actor,
        provider_user_id="different-provider-user",
    )
    with pytest.raises(ExternalAccountLinkActorMismatch):
        await repository.verify_candidate_code(
            actor=mismatched_actor,
            origin_id=origin.origin_id,
            code_hash=hashlib.sha256(b"wrong-code").hexdigest(),
            now=now,
        )
    loaded_origin = await repository.get_origin(
        user_id=fixture.user_id,
        origin_id=origin.origin_id,
        now=now,
    )
    assert loaded_origin.invalid_code_count == 0

    with pytest.raises(ExternalAccountLinkInvalidCode) as invalid:
        await repository.verify_candidate_code(
            actor=fixture.actor,
            origin_id=origin.origin_id,
            code_hash=hashlib.sha256(b"wrong-code").hexdigest(),
            now=now,
        )
    assert invalid.value.remaining_attempts == 4

    proof = await repository.verify_candidate_code(
        actor=fixture.actor,
        origin_id=origin.origin_id,
        code_hash=hashlib.sha256(b"browser-code").hexdigest(),
        now=now,
    )
    assert proof.status is ExternalAccountLinkCandidateStatus.PROVIDER_VERIFIED
    link = await repository.confirm_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        candidate_id=candidate.id,
        now=now,
    )
    assert link.state is ExternalAccountLinkState.ACTIVE
    assert link.provider_tenant_display_label == "Workspace Team"

    replay = await repository.confirm_candidate(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        candidate_id=candidate.id,
        now=now,
    )
    assert replay.id == link.id

    async with rdb_session_manager() as session:
        persisted_candidate = await session.get(
            RDBExternalAccountLinkCandidate,
            candidate.id,
        )
        assert persisted_candidate is not None
        assert (
            persisted_candidate.code_hash == hashlib.sha256(b"browser-code").hexdigest()
        )
        assert (
            await session.get(
                RDBExternalChannelPrincipal,
                fixture.actor.principal_id,
            )
            is not None
        )
        await WorkspaceUserRepository().delete(session, fixture.workspace_user_id)

    listed = await repository.list_links(user_id=fixture.user_id, now=now)
    assert [item.state for item in listed] == [ExternalAccountLinkState.ACTIVE]
    revoked = await repository.unlink(
        user_id=fixture.user_id,
        auth_session_id=fixture.auth_session_id,
        link_id=link.id,
        now=now,
    )
    assert revoked.state is ExternalAccountLinkState.REVOKED
    async with rdb_session_manager() as session:
        assert (
            await session.get(
                RDBExternalChannelPrincipal,
                fixture.actor.principal_id,
            )
            is not None
        )


@dataclasses.dataclass(frozen=True)
class _Fixture:
    actor: VerifiedExternalAccountActor
    workspace_id: str
    user_id: str
    auth_session_id: str
    workspace_user_id: str


async def _create_fixture(
    session_manager: SessionManager[AsyncSession],
) -> _Fixture:
    suffix = uuid4().hex
    async with session_manager() as session:
        workspace_result = await WorkspaceRepository().create(
            session,
            WorkspaceCreate(
                name="Link protocol workspace",
                handle=f"link-protocol-{suffix}",
            ),
        )
        assert isinstance(workspace_result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(
            session,
            f"link-protocol-{suffix}",
        )
        assert workspace_id is not None
        user = await UserRepository().create(
            session,
            UserCreate(email=f"link-protocol-{suffix}@example.com"),
        )
        membership_result = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Link User",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(membership_result, Success)
        auth_session = await SessionRepository().create(
            session,
            SessionCreate(
                user_id=user.id,
                refresh_token=uuid4().hex + uuid4().hex,
                expires_at=datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC),
                max_expires_at=None,
                user_agent=None,
                ip_address=None,
            ),
        )
        external_repository = ExternalChannelRepository()
        connection = await external_repository.create_connection(
            session,
            ExternalChannelConnectionCreate(
                workspace_id=workspace_id,
                provider=ExternalChannelProvider.SLACK,
                transport=ExternalChannelTransport.HTTP,
                ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
                configuration_generation=1,
                status=ExternalChannelConnectionStatus.ACTIVE,
                app_mode=ExternalChannelAppMode.SINGLE,
                provider_app_id="app-" + suffix,
                provider_tenant_id="team-" + suffix,
                provider_bot_user_id=None,
                http_callback_selector_hash=None,
                encrypted_credentials="ciphertext",
                capabilities=None,
                provider_config=None,
                last_verified_at=None,
                last_health_at=None,
                last_health_code=None,
                disconnected_at=None,
                socket_lease_owner=None,
                socket_lease_until=None,
                socket_heartbeat_at=None,
                socket_gap_detected_at=None,
                socket_gap_reason=None,
            ),
        )
        principal = await external_repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="team-" + suffix,
                provider_user_id="external-user-" + suffix,
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name="External User",
                avatar_url=None,
                profile=None,
            ),
        )
    return _Fixture(
        actor=VerifiedExternalAccountActor(
            connection_id=connection.id,
            connection_configuration_generation=1,
            principal_id=principal.id,
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="team-" + suffix,
            provider_tenant_display_label="Workspace Team",
            provider_user_id="external-user-" + suffix,
            provider_display_label="External User",
            provider_interaction_id="interaction-" + suffix,
            provider_channel_id="channel-" + suffix,
            provider_thread_id=None,
        ),
        workspace_id=workspace_id,
        user_id=user.id,
        auth_session_id=auth_session.id,
        workspace_user_id=membership_result.value.id,
    )


async def _cleanup_link_test_rows(
    engine: AsyncEngine,
) -> None:
    """Delete only account-link fixtures that escaped the outer test transaction."""
    workspace_ids = sa.select(RDBWorkspace.id).where(
        RDBWorkspace.handle.like("link-protocol-%")
    )
    user_ids = (
        sa.select(RDBUser.id)
        .join(RDBUserEmail, RDBUserEmail.user_id == RDBUser.id)
        .where(
            sa.or_(
                RDBUserEmail.email.like("link-protocol-%@example.com"),
                RDBUserEmail.email.like("link-conflict-%@example.com"),
            )
        )
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.execute(
            sa.delete(RDBExternalAccountLinkOrigin).where(
                RDBExternalAccountLinkOrigin.workspace_id.in_(workspace_ids)
            )
        )
        await session.execute(
            sa.delete(RDBExternalAccountLink).where(
                RDBExternalAccountLink.workspace_id.in_(workspace_ids)
            )
        )
        await session.execute(
            sa.delete(RDBExternalChannelConnection).where(
                RDBExternalChannelConnection.workspace_id.in_(workspace_ids)
            )
        )
        await session.execute(
            sa.delete(RDBExternalChannelPrincipal).where(
                RDBExternalChannelPrincipal.provider_user_id.like("external-user-%")
            )
        )
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                sa.or_(
                    RDBWorkspaceUser.workspace_id.in_(workspace_ids),
                    RDBWorkspaceUser.user_id.in_(user_ids),
                )
            )
        )
        await session.execute(
            sa.delete(RDBSession).where(RDBSession.user_id.in_(user_ids))
        )
        await session.execute(sa.delete(RDBUser).where(RDBUser.id.in_(user_ids)))
        await session.execute(
            sa.delete(RDBWorkspace).where(RDBWorkspace.id.in_(workspace_ids))
        )
        await session.commit()
