"""Runtime Provider bootstrap reconciliation service tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)
from azents.core.platform_runtime_system_setting import PlatformRuntimeConfig
from azents.core.system_setting import SystemSettingSection
from azents.rdb.session import SessionManager
from azents.repos.runtime_provider.data import RuntimeProviderCreate
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingCreate,
)
from azents.repos.runtime_provider_binding.repository import (
    RuntimeProviderAuthBindingRepository,
)
from azents.repos.system_setting.repository import SystemSettingRepository

from .data import (
    RuntimeProviderBootstrapAuthenticationInput,
    RuntimeProviderBootstrapDeclarationInput,
    RuntimeProviderBootstrapSnapshot,
)
from .service import RuntimeProviderBootstrapService


def _snapshot(
    *,
    source_key: str = "helm/default/azents",
    source_revision: str = "revision-1",
    declarations: tuple[RuntimeProviderBootstrapDeclarationInput, ...] | None = None,
) -> RuntimeProviderBootstrapSnapshot:
    """Build one authoritative source snapshot for tests."""
    return RuntimeProviderBootstrapSnapshot(
        source_key=source_key,
        adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
        source_revision=source_revision,
        source_digest=f"digest-{source_revision}",
        declarations=(
            declarations
            if declarations is not None
            else (
                RuntimeProviderBootstrapDeclarationInput(
                    declaration_key="runtime-provider-kubernetes",
                    provider_logical_id="system-kubernetes",
                    kind=RuntimeProviderKind.KUBERNETES,
                    display_name="Kubernetes",
                    enabled=True,
                    availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                    capabilities={},
                    config_schema=None,
                    metadata=None,
                    creation_seeds={"set_as_platform_default_when_unset": True},
                    authentication=RuntimeProviderBootstrapAuthenticationInput(
                        method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                        subject="system:serviceaccount:azents:azents-runtime-provider",
                        namespace="azents",
                        serviceAccountName="azents-runtime-provider",
                        audience="azents-runtime-control",
                    ),
                ),
            )
        ),
    )


@asynccontextmanager
async def _session_context(
    session: AsyncSession,
) -> AsyncGenerator[AsyncSession, None]:
    """Expose one test session through the production SessionManager shape."""
    yield session


def _single_session_manager(session: AsyncSession) -> SessionManager[AsyncSession]:
    """Build a production-shaped SessionManager for one test session."""
    return lambda: _session_context(session)


class TestRuntimeProviderBootstrapService:
    """Verify trusted source reconciliation invariants."""

    async def test_creates_bootstrap_provider_and_is_idempotent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A matching second snapshot reuses the original aggregate."""
        repository = RuntimeProviderRepository()
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )

        first = await service.reconcile(_snapshot())
        second = await service.reconcile(_snapshot(source_revision="revision-2"))

        assert len(first.created_provider_ids) == 1
        assert second.created_provider_ids == ()
        assert second.conflicted_declaration_keys == ()
        provider = await repository.get_by_provider_id(
            rdb_session,
            provider_logical_id="system-kubernetes",
            for_update=False,
        )
        assert provider is not None
        declaration = await repository.get_bootstrap_declaration(
            rdb_session,
            source_id=first.source_id,
            declaration_key="runtime-provider-kubernetes",
            for_update=False,
        )
        assert declaration is not None
        assert declaration.provider_id == provider.id
        assert declaration.state == RuntimeProviderBootstrapDeclarationState.PRESENT
        assert declaration.source_revision == "revision-2"
        assert (
            provider.registration_method == RuntimeProviderRegistrationMethod.BOOTSTRAP
        )
        binding_repository = RuntimeProviderAuthBindingRepository()
        bindings = await binding_repository.list_for_provider(
            rdb_session,
            provider_id=provider.id,
        )
        assert len(bindings) == 1
        assert bindings[0].subject == (
            "system:serviceaccount:azents:azents-runtime-provider"
        )
        assert bindings[0].config == {
            "namespace": "azents",
            "service_account_name": "azents-runtime-provider",
            "audience": "azents-runtime-control",
        }
        audit_events = await binding_repository.list_audit_events(
            rdb_session,
            binding_id=bindings[0].id,
            offset=0,
            limit=10,
        )
        assert [event.event_type for event in audit_events] == [
            RuntimeProviderBindingAuditEventType.RECONCILED,
            RuntimeProviderBindingAuditEventType.CREATED,
        ]
        platform_runtime = await SystemSettingRepository().get_current(
            rdb_session,
            section=SystemSettingSection.PLATFORM_RUNTIME,
        )
        assert platform_runtime is not None
        assert (
            PlatformRuntimeConfig.model_validate(
                platform_runtime.config
            ).default_provider_id
            == "system-kubernetes"
        )

    async def test_conflicts_without_adopting_admin_provider(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Bootstrap must never adopt an aggregate created by an Admin."""
        repository = RuntimeProviderRepository()
        await repository.create(
            rdb_session,
            RuntimeProviderCreate(
                provider_id="admin-kubernetes",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Admin Kubernetes",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )

        result = await service.reconcile(
            _snapshot(
                declarations=(
                    RuntimeProviderBootstrapDeclarationInput(
                        declaration_key="admin-provider-claim",
                        provider_logical_id="admin-kubernetes",
                        kind=RuntimeProviderKind.KUBERNETES,
                        display_name="Claimed Kubernetes",
                        enabled=True,
                        availability_mode=(
                            RuntimeProviderAvailabilityMode.PLATFORM_WIDE
                        ),
                        capabilities={},
                        config_schema=None,
                        metadata=None,
                        creation_seeds=None,
                        authentication=RuntimeProviderBootstrapAuthenticationInput(
                            method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                            subject="system:serviceaccount:azents:admin-provider",
                            namespace="azents",
                            serviceAccountName="admin-provider",
                            audience="azents-runtime-control",
                        ),
                    ),
                )
            )
        )

        assert result.created_provider_ids == ()
        assert result.conflicted_declaration_keys == ("admin-provider-claim",)
        declaration = await repository.get_bootstrap_declaration(
            rdb_session,
            source_id=result.source_id,
            declaration_key="admin-provider-claim",
            for_update=False,
        )
        assert declaration is not None
        assert declaration.provider_id is None
        assert declaration.state == RuntimeProviderBootstrapDeclarationState.CONFLICT
        assert declaration.conflict_code == "provider_owned_by_admin"

    async def test_auth_subject_conflict_does_not_create_provider(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A pre-owned auth subject cannot leave a new orphan Provider."""
        repository = RuntimeProviderRepository()
        existing_provider = await repository.create(
            rdb_session,
            RuntimeProviderCreate(
                provider_id="existing-auth-owner",
                scope=RuntimeProviderScope.SYSTEM,
                workspace_id=None,
                kind=RuntimeProviderKind.KUBERNETES,
                display_name="Existing Auth Owner",
                registration_method=RuntimeProviderRegistrationMethod.ADMIN,
                enabled=True,
                lifecycle_state=RuntimeProviderLifecycleState.ACTIVE,
                availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
                capabilities={},
                config_schema=None,
                metadata=None,
            ),
        )
        binding_repository = RuntimeProviderAuthBindingRepository()
        await binding_repository.create(
            rdb_session,
            create=RuntimeProviderAuthBindingCreate(
                provider_id=existing_provider.id,
                auth_method=RuntimeProviderAuthMethod.KUBERNETES_SERVICE_ACCOUNT,
                subject="system:serviceaccount:azents:azents-runtime-provider",
                owner=RuntimeProviderBindingOwner.ADMIN,
                bootstrap_declaration_id=None,
                config={
                    "namespace": "azents",
                    "service_account_name": "azents-runtime-provider",
                    "audience": "azents-runtime-control",
                },
            ),
        )
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=binding_repository,
        )

        result = await service.reconcile(_snapshot())

        assert result.created_provider_ids == ()
        assert result.conflicted_declaration_keys == ("runtime-provider-kubernetes",)
        assert (
            await repository.get_by_provider_id(
                rdb_session,
                provider_logical_id="system-kubernetes",
                for_update=False,
            )
            is None
        )

    async def test_conflicts_when_authentication_config_changes(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A declaration cannot silently replace its bound authentication config."""
        repository = RuntimeProviderRepository()
        binding_repository = RuntimeProviderAuthBindingRepository()
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=binding_repository,
        )
        initial_snapshot = _snapshot()
        initial = await service.reconcile(initial_snapshot)
        declaration = initial_snapshot.declarations[0]
        assert declaration.authentication is not None
        changed = declaration.model_copy(
            update={
                "authentication": declaration.authentication.model_copy(
                    update={"audience": "different-audience"}
                )
            }
        )

        result = await service.reconcile(
            _snapshot(source_revision="revision-2", declarations=(changed,))
        )

        assert result.conflicted_declaration_keys == ("runtime-provider-kubernetes",)
        binding = (
            await binding_repository.list_for_provider(
                rdb_session,
                provider_id=initial.created_provider_ids[0],
            )
        )[0]
        assert binding.state is RuntimeProviderBindingState.ACTIVE
        assert binding.config == {
            "namespace": "azents",
            "service_account_name": "azents-runtime-provider",
            "audience": "azents-runtime-control",
        }

    async def test_conflicts_without_adopting_other_source_provider(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A source cannot claim the logical identity owned by another source."""
        repository = RuntimeProviderRepository()
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )
        first = await service.reconcile(_snapshot(source_key="helm/one/azents"))
        second = await service.reconcile(_snapshot(source_key="helm/two/azents"))

        assert len(first.created_provider_ids) == 1
        assert second.created_provider_ids == ()
        assert second.conflicted_declaration_keys == ("runtime-provider-kubernetes",)
        declaration = await repository.get_bootstrap_declaration(
            rdb_session,
            source_id=second.source_id,
            declaration_key="runtime-provider-kubernetes",
            for_update=False,
        )
        assert declaration is not None
        assert declaration.provider_id is None
        assert declaration.conflict_code == "provider_owned_by_different_source"

    async def test_authoritative_omission_marks_declaration_absent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Withdrawal preserves the aggregate and records declaration absence."""
        repository = RuntimeProviderRepository()
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )
        initial = await service.reconcile(_snapshot())

        withdrawn = await service.reconcile(
            _snapshot(source_revision="revision-2", declarations=())
        )

        assert withdrawn.withdrawn_provider_ids == initial.created_provider_ids
        provider = await repository.get_by_provider_id(
            rdb_session,
            provider_logical_id="system-kubernetes",
            for_update=False,
        )
        assert provider is not None
        declaration = await repository.get_bootstrap_declaration(
            rdb_session,
            source_id=initial.source_id,
            declaration_key="runtime-provider-kubernetes",
            for_update=False,
        )
        assert declaration is not None
        assert declaration.provider_id == provider.id
        assert declaration.state == RuntimeProviderBootstrapDeclarationState.ABSENT
        assert declaration.withdrawn_at is not None
        binding = (
            await RuntimeProviderAuthBindingRepository().list_for_provider(
                rdb_session,
                provider_id=provider.id,
            )
        )[0]
        assert binding.state is RuntimeProviderBindingState.REVOKED

    async def test_terminal_provider_is_not_restored_by_bootstrap(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A force-retired logical identity remains reserved after source return."""
        repository = RuntimeProviderRepository()
        service = RuntimeProviderBootstrapService(
            session_manager=_single_session_manager(rdb_session),
            repository=repository,
            system_setting_repository=SystemSettingRepository(),
            binding_repository=RuntimeProviderAuthBindingRepository(),
        )
        initial = await service.reconcile(_snapshot())
        provider_id = initial.created_provider_ids[0]
        updated = await repository.update_administrative_policy(
            rdb_session,
            provider_id=provider_id,
            enabled=False,
            lifecycle_state=RuntimeProviderLifecycleState.FORCE_RETIRED,
            availability_mode=RuntimeProviderAvailabilityMode.PLATFORM_WIDE,
        )
        assert updated is not None

        result = await service.reconcile(_snapshot(source_revision="revision-2"))

        assert result.created_provider_ids == ()
        assert result.conflicted_declaration_keys == ("runtime-provider-kubernetes",)
        declaration = await repository.get_bootstrap_declaration(
            rdb_session,
            source_id=initial.source_id,
            declaration_key="runtime-provider-kubernetes",
            for_update=False,
        )
        assert declaration is not None
        assert declaration.state == RuntimeProviderBootstrapDeclarationState.CONFLICT
        assert declaration.conflict_code == "provider_terminal"
