"""Native PostgreSQL completion, atomicity and read-only residual boundaries."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Never
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.credentials import KimiOAuthConfig, KimiOAuthSecrets
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
    LLMCatalogPurpose,
    LLMProvider,
)
from azents.core.external_channel_title import DISCORD_INITIAL_THREAD_TITLE_LABEL
from azents.core.kimi_oauth import KimiOAuthConnectionMethod, KimiOAuthSessionStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelInteraction,
    RDBExternalChannelPrincipal,
    RDBExternalChannelResource,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.admission_operations import (
    ExternalChannelAdmissionOperations,
)
from azents.repos.external_channel.data import (
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.http_admission_read import (
    ExternalChannelHTTPAdmissionReadRepository,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_recovery_read import (
    ExternalChannelIngressRecoveryReadRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import _create_workspace
from azents.repos.external_channel.thread_title_read import (
    ExternalChannelThreadTitleReadRepository,
)
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
)
from azents.repos.kimi_oauth_session.data import KimiOAuthSessionCreate
from azents.repos.kimi_oauth_session.operations import KimiOAuthOperations
from azents.repos.kimi_oauth_session.repository import KimiOAuthSessionRepository
from azents.repos.llm_catalog import LLMCatalogRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationCreate
from azents.repos.llm_provider_integration.operations import (
    LLMProviderIntegrationOperations,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


@dataclass
class _ObservedReadManager:
    """Prove native PostgreSQL RO state and closure at operation return."""

    manager: SessionManager[ReadSession]
    active: int = 0
    closed: int = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[ReadSession]:
        async with self.manager() as session:
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            self.active += 1
            try:
                yield session
            finally:
                self.active -= 1
        self.closed += 1


class _AdmissionFailure(ExternalChannelRepository):
    """Fail after both actual rows were flushed to require rollback."""

    async def admit_interaction(
        self, session: WriteSession, create: ExternalChannelInteractionCreate
    ) -> ExternalChannelInteractionAdmission:
        await super().admit_interaction(session, create)
        raise RuntimeError("synthetic admission rollback")


@pytest.mark.parametrize("fail", [False, True])
async def test_admission_operation_commits_or_rolls_back_principal_and_interaction(
    rdb_engine: AsyncEngine, latest_db_schema: None, fail: bool
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = _AdmissionFailure() if fail else ExternalChannelRepository()
    operations = ExternalChannelAdmissionOperations(writes, repository)
    key = uuid4().hex
    now = datetime.datetime.now(datetime.UTC)
    create = ExternalChannelInteractionCreate(
        connection_id=seeded.connection_id,
        transport=ExternalChannelTransport.HTTP,
        provider_interaction_key=key,
        interaction_type=ExternalChannelInteractionType.BLOCK_ACTION,
        callback_id=None,
        action_id=None,
        principal_id=None,
        setup_claim_id=None,
        resource_correlation_key=None,
        projection={},
        status=ExternalChannelInteractionStatus.ACCEPTED,
        expires_at=now + datetime.timedelta(minutes=10),
        error_kind=None,
        error_summary=None,
    )
    principal = ExternalChannelPrincipalCreate(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id=f"tenant-{seeded.workspace_id[3:]}",
        provider_user_id=key,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        display_name=None,
        avatar_url=None,
        profile=None,
    )
    try:
        if fail:
            with pytest.raises(RuntimeError, match="synthetic admission rollback"):
                await operations.admit_interaction(create=create, principal=principal)
        else:
            admitted = await operations.admit_interaction(
                create=create, principal=principal
            )
            assert admitted.created
            claim = await operations.begin_interaction_provider_mutation(
                interaction_id=admitted.interaction.id,
                now=now,
                processing_lease=datetime.timedelta(minutes=6),
            )
            assert claim is not None and claim.claimed
            duplicate = await operations.begin_interaction_provider_mutation(
                interaction_id=admitted.interaction.id,
                now=now,
                processing_lease=datetime.timedelta(minutes=6),
            )
            assert duplicate is not None and not duplicate.claimed
        async with reads() as session:
            persisted = await session.read_session.scalar(
                sa.select(RDBExternalChannelPrincipal.id).where(
                    RDBExternalChannelPrincipal.provider_user_id == key
                )
            )
            assert (persisted is None) is fail
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelInteraction).where(
                    RDBExternalChannelInteraction.connection_id == seeded.connection_id
                )
            )
        await _cleanup_binding(rdb_engine, seeded)
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelPrincipal).where(
                    RDBExternalChannelPrincipal.provider_user_id == key
                )
            )


async def test_channel_descriptive_reads_close_native_ro_before_return(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    observed = _ObservedReadManager(create_read_only_session_manager(rdb_engine))
    repository = ExternalChannelRepository()
    assert (
        await ExternalChannelHTTPAdmissionReadRepository(
            session_manager=observed, repository=repository
        ).get_discord_configuration(selector_hash=uuid4().hex)
        is None
    )
    assert observed.active == 0 and observed.closed == 1
    await ExternalChannelIngressRecoveryReadRepository(
        observed, ExternalChannelIngressQueueRepository()
    ).list_recoverable_owners(now=datetime.datetime.now(datetime.UTC), limit=1)
    assert observed.active == 0 and observed.closed == 2
    assert (
        await ExternalChannelThreadTitleReadRepository(
            observed, repository, AgentRepository(), AgentSessionRepository()
        ).load_authority(
            session_id=uuid4().hex,
            resource_id=uuid4().hex,
            binding_id=uuid4().hex,
            provider_tenant_id=uuid4().hex,
        )
        is None
    )
    assert observed.active == 0 and observed.closed == 3


class _IntegrationFailure(LLMProviderIntegrationRepository):
    """Force actual integration flush failure after consume to test rollback."""

    async def create(
        self, session: WriteSession, create: LLMProviderIntegrationCreate
    ) -> Never:
        await super().create(session, create)
        raise RuntimeError("synthetic integration rollback")


@pytest.mark.parametrize("fail", [False, True])
async def test_kimi_consume_and_integration_persistence_are_one_completed_transaction(
    rdb_engine: AsyncEngine, latest_db_schema: None, fail: bool
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = _ObservedReadManager(create_read_only_session_manager(rdb_engine))
    cipher = CredentialCipher(Fernet.generate_key().decode())
    sessions = KimiOAuthSessionRepository(cipher)
    integrations = (
        _IntegrationFailure(cipher)
        if fail
        else LLMProviderIntegrationRepository(cipher)
    )
    operations = KimiOAuthOperations(writes, sessions, integrations, reads)
    now = datetime.datetime.now(datetime.UTC)
    async with writes() as session:
        workspace_id = await _create_workspace(session, uuid4().hex)
        user = await UserRepository().create(
            session, UserCreate(email=f"{uuid4().hex}@example.com")
        )
    try:
        created = await operations.create(
            KimiOAuthSessionCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                method=KimiOAuthConnectionMethod.DEVICE,
                device_code="device",
                device_id="identity",
                user_code="user",
                verification_uri="https://example.com",
                interval_seconds=5,
                expires_at=now + datetime.timedelta(minutes=10),
            )
        )
        secrets = KimiOAuthSecrets(
            access_token="access",
            refresh_token="refresh",
            expires_at=now + datetime.timedelta(hours=1),
            device_id="identity",
        )
        config = KimiOAuthConfig(
            connection_method="device",
            status="connected",
            connected_at=now,
            last_refreshed_at=now,
            last_failed_at=None,
            last_failure_reason=None,
        )
        if fail:
            with pytest.raises(RuntimeError, match="synthetic integration rollback"):
                await operations.consume_and_save_tokens(
                    workspace_id=workspace_id,
                    session_id=created.id,
                    secrets=secrets,
                    config=config,
                )
        else:
            result = await operations.consume_and_save_tokens(
                workspace_id=workspace_id,
                session_id=created.id,
                secrets=secrets,
                config=config,
            )
            assert isinstance(result, Success)
        loaded = await operations.get_by_id_with_secrets(created.id)
        assert loaded is not None
        assert loaded.status is (
            KimiOAuthSessionStatus.PENDING if fail else KimiOAuthSessionStatus.CONNECTED
        )
        assert reads.active == 0 and reads.closed == 1
        async with reads() as session:
            listed = await integrations.list_by_workspace(session, workspace_id)
        assert len(listed.items) == (0 if fail else 1)
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
            await UserRepository().delete(session, user.id)


class _CatalogFailure(LLMCatalogRepository):
    """Require account catalog failure to roll back the integration create."""

    async def ensure_integration_catalog(
        self,
        session: WriteSession,
        *,
        integration_id: str,
        provider: LLMProvider,
        purpose: LLMCatalogPurpose,
    ) -> Never:
        del session, integration_id, provider, purpose
        raise RuntimeError("synthetic catalog rollback")


async def test_integration_catalog_failure_rolls_back_completed_create(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = _ObservedReadManager(create_read_only_session_manager(rdb_engine))
    repository = LLMProviderIntegrationRepository(
        CredentialCipher(Fernet.generate_key().decode())
    )
    operations = LLMProviderIntegrationOperations(
        repository, _CatalogFailure(), writes, reads
    )
    now = datetime.datetime.now(datetime.UTC)
    async with writes() as session:
        workspace_id = await _create_workspace(session, uuid4().hex)
    try:
        with pytest.raises(RuntimeError, match="synthetic catalog rollback"):
            await operations.create(
                LLMProviderIntegrationCreate(
                    workspace_id=workspace_id,
                    provider=LLMProvider.KIMI_OAUTH,
                    name="Kimi",
                    secrets=KimiOAuthSecrets(
                        access_token="access",
                        refresh_token="refresh",
                        expires_at=now,
                        device_id="identity",
                    ),
                    config=None,
                )
            )
        listed = await operations.list_by_workspace(workspace_id)
        assert listed.items == [] and reads.active == 0 and reads.closed == 1
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )


async def test_thread_title_exact_authority_is_ro_and_disconnected_binding_fails_closed(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = _ObservedReadManager(create_read_only_session_manager(rdb_engine))
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    selection = make_test_model_selection_dict()
    repository = ExternalChannelThreadTitleReadRepository(
        reads, ExternalChannelRepository(), AgentRepository(), AgentSessionRepository()
    )
    try:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == seeded.owner_agent_id)
                .values(
                    model_selection=selection,
                    lightweight_model_selection=selection,
                    selectable_model_options=make_test_selectable_model_option_dicts(
                        model_selection=selection, lightweight_model_selection=selection
                    ),
                    main_model_label="default",
                    lightweight_model_label="lightweight",
                )
            )
            await session.write_session.execute(
                sa.update(RDBExternalChannelConnection)
                .where(RDBExternalChannelConnection.id == seeded.connection_id)
                .values(
                    provider=ExternalChannelProvider.DISCORD,
                    provider_tenant_id="100",
                    encrypted_credentials="encrypted-title-only",
                )
            )
            await session.write_session.execute(
                sa.update(RDBExternalChannelResource)
                .where(RDBExternalChannelResource.id == seeded.resource_id)
                .values(
                    labels={
                        "provider": "discord",
                        "guild_id": "100",
                        "delivery_channel_id": "444",
                        DISCORD_INITIAL_THREAD_TITLE_LABEL: "Provisional",
                    }
                )
            )
        snapshot = await repository.load_authority(
            session_id=seeded.owner_session_id,
            resource_id=seeded.resource_id,
            binding_id=seeded.binding_id,
            provider_tenant_id="100",
        )
        assert snapshot is not None
        assert snapshot.encrypted_credentials == "encrypted-title-only"
        assert (
            snapshot.channel_id == "444" and snapshot.provisional_title == "Provisional"
        )
        assert reads.active == 0 and reads.closed == 1
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelBinding)
                .where(RDBExternalChannelBinding.id == seeded.binding_id)
                .values(disconnected_at=datetime.datetime.now(datetime.UTC))
            )
        assert (
            await repository.load_authority(
                session_id=seeded.owner_session_id,
                resource_id=seeded.resource_id,
                binding_id=seeded.binding_id,
                provider_tenant_id="100",
            )
            is None
        )
        assert reads.active == 0 and reads.closed == 2
    finally:
        await _cleanup_binding(rdb_engine, seeded)
