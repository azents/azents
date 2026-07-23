"""Runtime Provider authentication binding Admin lifecycle tests."""

import datetime
import json
from typing import Any

import pytest
from azcommon.datetime import tznow
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderEnrollmentGrantState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.runtime_provider_credential import RuntimeProviderCredentialVerifier
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingCreate,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.runtime_provider_control.repository import (
    RuntimeProviderControlRepository,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.runtime_provider_control.data import (
    RuntimeProviderCredentialUnavailable,
)
from azents.services.runtime_provider_control.service import (
    RuntimeProviderEnrollmentService,
)

from .service import (
    RuntimeProviderBindingAdminService,
    RuntimeProviderBindingAdminUnavailable,
)


def _enrollment_service(
    session_manager: SessionManager[AsyncSession],
) -> RuntimeProviderEnrollmentService:
    """Build the issued-token enrollment service used by Admin rotation."""
    return RuntimeProviderEnrollmentService(
        session_manager=session_manager,
        repository=RuntimeProviderControlRepository(),
        provider_repository=RuntimeProviderRepository(),
        binding_repository=RuntimeProviderAuthBindingRepository(),
        verifier=RuntimeProviderCredentialVerifier(Fernet.generate_key().decode()),
        kubernetes_token_reviewer=None,
        auth_registry=None,
    )


def _service(
    session_manager: SessionManager[AsyncSession],
    enrollment_service: RuntimeProviderEnrollmentService,
) -> RuntimeProviderBindingAdminService:
    """Build the binding Admin service with production repositories."""
    return RuntimeProviderBindingAdminService(
        session_manager=session_manager,
        provider_repository=RuntimeProviderRepository(),
        binding_repository=RuntimeProviderAuthBindingRepository(),
        control_repository=RuntimeProviderControlRepository(),
        enrollment_service=enrollment_service,
    )


async def _create_admin_and_provider(
    session_manager: SessionManager[AsyncSession],
    *,
    provider_logical_id: str,
    lifecycle_state: RuntimeProviderLifecycleState = (
        RuntimeProviderLifecycleState.ACTIVE
    ),
) -> tuple[str, str]:
    """Create one Admin actor and one Provider aggregate."""
    async with session_manager() as session:
        user = await UserRepository().create(
            session,
            UserCreate(email=f"{provider_logical_id}@example.com"),
        )
        provider = await RuntimeProviderRepository().create(
            session,
            RuntimeProviderCreate(
                provider_id=provider_logical_id,
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.DOCKER,
                display_name=provider_logical_id,
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=lifecycle_state,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
    return user.id, provider.id


class TestRuntimeProviderBindingAdminService:
    """Verify binding lifecycle, safe projections, and authority revocation."""

    async def test_create_rotate_revoke_and_audit_lifecycle(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Admin lifecycle is atomic, optimistic, and secret-safe."""
        actor_user_id, _ = await _create_admin_and_provider(
            rdb_session_manager,
            provider_logical_id="admin-binding-provider",
        )
        enrollment_service = _enrollment_service(rdb_session_manager)
        service = _service(rdb_session_manager, enrollment_service)
        binding = await service.create_binding(
            "admin-binding-provider",
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject="  provider:admin-binding-provider:admin  ",
            config=None,
            actor_user_id=actor_user_id,
        )

        assert binding.provider_id == "admin-binding-provider"
        assert binding.binding.subject == "provider:admin-binding-provider:admin"
        assert binding.binding.owner is RuntimeProviderBindingOwner.ADMIN
        assert binding.binding.config is None
        assert binding.binding.admin_version == 1

        first_rotation = await service.rotate_binding(
            binding.binding.id,
            expected_admin_version=1,
            expires_at=tznow() + datetime.timedelta(minutes=10),
            actor_user_id=actor_user_id,
        )
        assert first_rotation.binding.binding.admin_version == 2
        assert first_rotation.secret

        with pytest.raises(
            RuntimeProviderBindingAdminUnavailable,
            match="stale_binding_version",
        ) as stale_rotation:
            await service.rotate_binding(
                binding.binding.id,
                expected_admin_version=1,
                expires_at=tznow() + datetime.timedelta(minutes=10),
                actor_user_id=actor_user_id,
            )
        assert stale_rotation.value.current_binding is not None
        assert stale_rotation.value.current_binding.binding.admin_version == 2

        credential = await enrollment_service.exchange_grant(
            grant_id=first_rotation.grant_id,
            secret=first_rotation.secret,
            credential_expires_at=None,
            source_address=None,
        )
        authentication = await enrollment_service.authenticate_credential(
            secret=credential.secret
        )
        connected_at = tznow()
        await enrollment_service.create_connection(
            authentication=authentication,
            connection_id="admin-binding-provider-connection",
            generation=1,
            reported_provider_type="docker",
            reported_protocol_version="test-v1",
            connected_at=connected_at,
        )
        assert (await service.get_binding(binding.binding.id)).connected

        second_rotation = await service.rotate_binding(
            binding.binding.id,
            expected_admin_version=2,
            expires_at=tznow() + datetime.timedelta(minutes=10),
            actor_user_id=actor_user_id,
        )
        assert second_rotation.binding.binding.admin_version == 3
        assert await enrollment_service.authenticate_credential(
            secret=credential.secret
        )

        with pytest.raises(
            RuntimeProviderBindingAdminUnavailable,
            match="stale_binding_version",
        ) as stale_revoke:
            await service.revoke_binding(
                binding.binding.id,
                expected_admin_version=2,
                reason="stale request",
                actor_user_id=actor_user_id,
            )
        assert stale_revoke.value.current_binding is not None
        assert stale_revoke.value.current_binding.binding.admin_version == 3

        revoked = await service.revoke_binding(
            binding.binding.id,
            expected_admin_version=3,
            reason="operator requested",
            actor_user_id=actor_user_id,
        )
        assert revoked.binding.state is RuntimeProviderBindingState.REVOKED
        assert revoked.binding.admin_version == 4
        assert revoked.binding.revoked_by_user_id == actor_user_id
        assert revoked.binding.revocation_reason == "operator requested"
        assert not revoked.connected

        with pytest.raises(RuntimeProviderCredentialUnavailable):
            await enrollment_service.authenticate_credential(secret=credential.secret)
        assert not await enrollment_service.connection_active(
            authentication=authentication,
            generation=1,
            now=connected_at + datetime.timedelta(seconds=1),
        )
        async with rdb_session_manager() as session:
            control_repository = RuntimeProviderControlRepository()
            outstanding_grant = (
                await control_repository.get_enrollment_grant_for_update(
                    session,
                    grant_id=second_rotation.grant_id,
                )
            )
        assert outstanding_grant is not None
        assert outstanding_grant.state is RuntimeProviderEnrollmentGrantState.REVOKED

        listed = await service.list_bindings("admin-binding-provider")
        assert [item.binding.id for item in listed] == [binding.binding.id]
        assert listed[0].binding.state is RuntimeProviderBindingState.REVOKED
        events = await service.list_audit_events(
            binding.binding.id,
            offset=0,
            limit=10,
        )
        assert [event.event_type for event in events] == [
            RuntimeProviderBindingAuditEventType.REVOKED,
            RuntimeProviderBindingAuditEventType.ROTATED,
            RuntimeProviderBindingAuditEventType.ROTATED,
            RuntimeProviderBindingAuditEventType.CREATED,
        ]
        serialized_metadata = json.dumps([event.metadata for event in events])
        assert first_rotation.secret not in serialized_metadata
        assert second_rotation.secret not in serialized_metadata
        assert credential.secret not in serialized_metadata

    async def test_bootstrap_binding_is_read_only_and_config_is_redacted(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Admin reads only safe workload metadata and cannot mutate ownership."""
        actor_user_id, provider_id = await _create_admin_and_provider(
            rdb_session_manager,
            provider_logical_id="bootstrap-binding-provider",
        )
        async with rdb_session_manager() as session:
            binding = await RuntimeProviderAuthBindingRepository().create(
                session,
                create=RuntimeProviderAuthBindingCreate(
                    provider_id=provider_id,
                    auth_method=(RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT),
                    subject="system:serviceaccount:azents:runtime-provider",
                    owner=RuntimeProviderBindingOwner.BOOTSTRAP,
                    bootstrap_declaration_id=None,
                    config={
                        "namespace": "azents",
                        "service_account_name": "runtime-provider",
                        "audience": "azents-runtime-control",
                        "unexpected_secret": "must-not-leak",
                    },
                ),
            )
        service = _service(
            rdb_session_manager,
            _enrollment_service(rdb_session_manager),
        )

        projection = await service.get_binding(binding.id)
        assert projection.binding.config == {
            "namespace": "azents",
            "service_account_name": "runtime-provider",
            "audience": "azents-runtime-control",
        }
        assert "must-not-leak" not in json.dumps(projection.binding.config)

        for operation in ("rotate", "revoke"):
            with pytest.raises(
                RuntimeProviderBindingAdminUnavailable,
                match="binding_read_only",
            ):
                if operation == "rotate":
                    await service.rotate_binding(
                        binding.id,
                        expected_admin_version=1,
                        expires_at=tznow() + datetime.timedelta(minutes=10),
                        actor_user_id=actor_user_id,
                    )
                else:
                    await service.revoke_binding(
                        binding.id,
                        expected_admin_version=1,
                        reason="not allowed",
                        actor_user_id=actor_user_id,
                    )

    async def test_create_rejects_invalid_or_conflicting_binding(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Creation rejects unsafe method/config, terminal Providers, and duplicates."""
        actor_user_id, _ = await _create_admin_and_provider(
            rdb_session_manager,
            provider_logical_id="binding-create-provider",
        )
        terminal_actor_user_id, _ = await _create_admin_and_provider(
            rdb_session_manager,
            provider_logical_id="terminal-binding-provider",
            lifecycle_state=RuntimeProviderLifecycleState.DECOMMISSIONED,
        )
        service = _service(
            rdb_session_manager,
            _enrollment_service(rdb_session_manager),
        )

        invalid_cases: tuple[
            tuple[
                RuntimeProviderAuthMethod,
                str,
                dict[str, Any] | None,
                str,
            ],
            ...,
        ] = (
            (
                RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                "system:serviceaccount:azents:runtime-provider",
                None,
                "unsupported_binding_method",
            ),
            (
                RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                "provider:binding-create-provider:admin",
                {"secret": "not-allowed"},
                "binding_config_invalid",
            ),
            (
                RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                "   ",
                None,
                "binding_subject_invalid",
            ),
        )
        for auth_method, subject, config, code in invalid_cases:
            with pytest.raises(
                RuntimeProviderBindingAdminUnavailable,
                match=code,
            ):
                await service.create_binding(
                    "binding-create-provider",
                    auth_method=auth_method,
                    subject=subject,
                    config=config,
                    actor_user_id=actor_user_id,
                )

        with pytest.raises(
            RuntimeProviderBindingAdminUnavailable,
            match="provider_unavailable",
        ):
            await service.create_binding(
                "terminal-binding-provider",
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                subject="provider:terminal-binding-provider:admin",
                config=None,
                actor_user_id=terminal_actor_user_id,
            )

        created = await service.create_binding(
            "binding-create-provider",
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject="provider:binding-create-provider:admin",
            config=None,
            actor_user_id=actor_user_id,
        )
        with pytest.raises(
            RuntimeProviderBindingAdminUnavailable,
            match="binding_conflict",
        ):
            await service.create_binding(
                "binding-create-provider",
                auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
                subject=created.binding.subject,
                config=None,
                actor_user_id=actor_user_id,
            )
        listed = await service.list_bindings("binding-create-provider")
        assert [item.binding.id for item in listed] == [created.binding.id]
