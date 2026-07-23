"""Runtime Provider authentication binding persistence tests."""

import datetime

from azcommon.datetime import tznow
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository

from .data import (
    RuntimeProviderAuthBindingAuditEventCreate,
    RuntimeProviderAuthBindingCreate,
    RuntimeProviderAuthBindingRevoke,
)
from .repository import RuntimeProviderAuthBindingRepository


async def _provider_id(session: AsyncSession) -> str:
    """Create one Provider aggregate for binding tests."""
    provider = await RuntimeProviderRepository().create(
        session,
        RuntimeProviderCreate(
            provider_id="provider-auth-binding-test",
            scope=RuntimeProviderScope.SYSTEM,
            workspace_id=None,
            kind=RuntimeProviderKind.DOCKER,
            display_name="Provider Auth Binding Test",
            registration_method=RuntimeProviderRegistrationMethod.ADMIN,
            enabled=True,
            lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
            capabilities={},
            config_schema=None,
            metadata=None,
        ),
    )
    return provider.id


class TestRuntimeProviderAuthBindingRepository:
    """Verify binding lifecycle, health timestamps, and audit persistence."""

    async def test_revoke_allows_subject_replacement_without_health_version_bump(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeProviderAuthBindingRepository()
        provider_id = await _provider_id(rdb_session)
        now = tznow()
        create = RuntimeProviderAuthBindingCreate(
            provider_id=provider_id,
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject=f"provider:{provider_id}:admin",
            owner=RuntimeProviderBindingOwner.ADMIN,
            bootstrap_declaration_id=None,
            config=None,
        )
        binding = await repository.create(rdb_session, create=create)

        assert binding.admin_version == 1
        assert await repository.mark_authenticated(
            rdb_session,
            binding_id=binding.id,
            authenticated_at=now,
        )
        assert await repository.mark_connected(
            rdb_session,
            binding_id=binding.id,
            connected_at=now + datetime.timedelta(seconds=1),
        )
        healthy = await repository.get_by_id(
            rdb_session,
            binding_id=binding.id,
            for_update=False,
        )
        assert healthy is not None
        assert healthy.admin_version == 1
        assert healthy.last_authenticated_at == now
        assert healthy.last_connected_at == now + datetime.timedelta(seconds=1)

        revoked = await repository.revoke(
            rdb_session,
            revoke=RuntimeProviderAuthBindingRevoke(
                binding_id=binding.id,
                expected_admin_version=1,
                revoked_at=now + datetime.timedelta(seconds=2),
                revoked_by_user_id=None,
                reason="test rotation",
            ),
        )
        assert revoked is not None
        assert revoked.state is RuntimeProviderBindingState.REVOKED
        assert revoked.admin_version == 2

        replacement = await repository.create(rdb_session, create=create)
        assert replacement.id != binding.id
        assert replacement.state is RuntimeProviderBindingState.ACTIVE
        assert replacement.admin_version == 1

    async def test_audit_events_are_metadata_only_and_newest_first(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        repository = RuntimeProviderAuthBindingRepository()
        provider_id = await _provider_id(rdb_session)
        binding = await repository.create(
            rdb_session,
            create=RuntimeProviderAuthBindingCreate(
                provider_id=provider_id,
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                subject=f"provider:{provider_id}:admin",
                owner=RuntimeProviderBindingOwner.ADMIN,
                bootstrap_declaration_id=None,
                config=None,
            ),
        )
        now = tznow()
        await repository.append_audit_event(
            rdb_session,
            create=RuntimeProviderAuthBindingAuditEventCreate(
                binding_id=binding.id,
                event_type=RuntimeProviderBindingAuditEventType.CREATED,
                actor_user_id=None,
                previous_admin_version=None,
                new_admin_version=1,
                metadata={"owner": "admin"},
                created_at=now,
            ),
        )
        await repository.append_audit_event(
            rdb_session,
            create=RuntimeProviderAuthBindingAuditEventCreate(
                binding_id=binding.id,
                event_type=RuntimeProviderBindingAuditEventType.AUTHENTICATED,
                actor_user_id=None,
                previous_admin_version=None,
                new_admin_version=None,
                metadata={"method": "azents_issued_token"},
                created_at=now + datetime.timedelta(seconds=1),
            ),
        )

        events = await repository.list_audit_events(
            rdb_session,
            binding_id=binding.id,
            offset=0,
            limit=10,
        )

        assert [event.event_type for event in events] == [
            RuntimeProviderBindingAuditEventType.AUTHENTICATED,
            RuntimeProviderBindingAuditEventType.CREATED,
        ]
        assert events[0].metadata == {"method": "azents_issued_token"}
