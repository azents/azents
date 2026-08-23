"""Runtime Provider inventory and authentication v1 Admin API tests."""

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from unittest.mock import AsyncMock, create_autospec

import pytest
from azents_runtime_control.provider import (
    RuntimeProviderOperationalDiagnostics,
    RuntimeProviderOperationalWarning,
    RuntimeProviderOperationalWarningSeverity,
)
from fastapi import APIRouter, FastAPI, HTTPException, params
from fastapi.routing import APIRoute
from pydantic import ValidationError

from azents.api.admin import mount as mount_admin
from azents.api.admin.runtime_provider.v1 import (
    create_provider_recreation,
    delete_pod_profile,
    get_auth_binding,
    get_platform_recreation,
    get_provider_diagnostics,
    mount,
    rotate_auth_binding,
)
from azents.api.admin.runtime_provider.v1.data import (
    RuntimeInfrastructureProfileDeleteRequest,
    RuntimeProviderAuthenticationBindingResponse,
    RuntimeProviderAuthenticationBindingRotateRequest,
)
from azents.api.runtime_recreation import RuntimeRecreationCreateRequest
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
)
from azents.core.runtime_profile import (
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)
from azents.repos.runtime_profile.data import (
    RuntimeInfrastructureProfileDeletion,
    RuntimeRecreationOperation,
    RuntimeRecreationOperationItem,
)
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBinding
from azents.services.runtime_profile_admin.service import (
    RuntimeProfileAdminService,
    RuntimeProfileAdminUnavailable,
)
from azents.services.runtime_provider_admin.service import (
    RuntimeProviderAdminService,
    RuntimeProviderOperationalDiagnosticsProjection,
)
from azents.services.runtime_provider_binding_admin.service import (
    RuntimeProviderBindingAdminProjection,
    RuntimeProviderBindingAdminService,
    RuntimeProviderBindingAdminUnavailable,
    RuntimeProviderBindingRotation,
)
from azents.services.runtime_recreation.service import (
    RuntimeRecreationProjection,
    RuntimeRecreationService,
    RuntimeRecreationUnavailable,
)
from azents.utils.fastapi.route import as_route_mounter


@dataclass(frozen=True)
class _MountedRoute:
    """One route plus dependencies applied by the enclosing API mount."""

    path: str
    methods: set[str] | None
    dependencies: Sequence[params.Depends]


def _mounted_admin_runtime_provider_routes() -> list[_MountedRoute]:
    """Capture effective Runtime Provider routes from the Admin API mounter."""
    mounted_routes: list[_MountedRoute] = []

    def capture(
        router: APIRouter,
        *,
        prefix: str,
        tag: str,
        description: str | None = None,
        dependencies: Sequence[params.Depends] | None = None,
    ) -> None:
        del tag, description
        if prefix != "/runtime-provider/v1":
            return
        for route in router.routes:
            if isinstance(route, APIRoute):
                mounted_routes.append(
                    _MountedRoute(
                        path=f"{prefix}{route.path}",
                        methods=route.methods,
                        dependencies=dependencies or (),
                    )
                )

    mount_admin(capture)
    return mounted_routes


def _projection(
    *,
    admin_version: int = 1,
) -> RuntimeProviderBindingAdminProjection:
    """Build one safe binding projection for route tests."""
    now = datetime.datetime(2026, 7, 23, tzinfo=datetime.UTC)
    return RuntimeProviderBindingAdminProjection(
        binding=RuntimeProviderAuthBinding(
            id="binding-1",
            provider_id="provider-row-1",
            auth_method=RuntimeProviderAuthMethod.AZENTS_ISSUED_TOKEN,
            subject="provider:provider-1:admin",
            state=RuntimeProviderBindingState.ACTIVE,
            owner=RuntimeProviderBindingOwner.ADMIN,
            bootstrap_declaration_id=None,
            config=None,
            admin_version=admin_version,
            last_authenticated_at=None,
            last_connected_at=None,
            revoked_at=None,
            revoked_by_user_id=None,
            revocation_reason=None,
            created_at=now,
            updated_at=now,
        ),
        provider_id="provider-1",
        connected=False,
    )


def _system_admin() -> SystemAdmin:
    """Create one authenticated System Admin context."""
    return SystemAdmin(user_id="admin-1", session_id="session-1")


def _recreation_operation() -> RuntimeRecreationOperation:
    """Build one Platform-scoped recreation operation."""
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperation(
        id="operation-1",
        target_kind=RuntimeRecreationTargetKind.PROVIDER,
        target_id="provider-row-1",
        target_version="4",
        status=RuntimeRecreationOperationStatus.COMPLETED_WITH_FAILURES,
        concurrency_limit=2,
        actor_user_id="admin-1",
        actor_workspace_user_id=None,
        total_count=2,
        pending_count=0,
        running_count=0,
        succeeded_count=1,
        skipped_count=0,
        failed_count=1,
        created_at=now,
        started_at=now,
        completed_at=now,
    )


def _recreation_item() -> RuntimeRecreationOperationItem:
    """Build one bounded Platform recreation failure detail."""
    now = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)
    return RuntimeRecreationOperationItem(
        id="item-1",
        operation_id="operation-1",
        runtime_id="runtime-1",
        expected_configuration_sequence=1,
        expected_configuration_digest="a" * 64,
        expected_desired_generation=5,
        status=RuntimeRecreationItemStatus.FAILED,
        attempt=3,
        dispatched_generation=5,
        failure_code="recreation_failed",
        failure_message="Runtime recreation failed.",
        created_at=now,
        updated_at=now,
    )


def test_mounts_runtime_provider_inventory_and_authentication_routes() -> None:
    """Expose Provider inventory, policy, availability, and binding routes."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = set(app.openapi()["paths"])

    assert "/runtime-provider/v1/providers" in paths
    assert "/runtime-provider/v1/providers/{provider_id}" in paths
    assert (
        "/runtime-provider/v1/providers/{provider_id}/operational-diagnostics" in paths
    )
    assert "/runtime-provider/v1/providers/{provider_id}/policy" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/availability" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/contracts" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/pod-profiles" in paths
    assert (
        "/runtime-provider/v1/providers/{provider_id}/pod-profiles/{profile_id}"
        in paths
    )
    assert "/runtime-provider/v1/providers/{provider_id}/container-profiles" in paths
    assert (
        "/runtime-provider/v1/providers/{provider_id}/container-profiles/{profile_id}"
        in paths
    )
    assert (
        "/runtime-provider/v1/providers/{provider_id}/pod-profiles/{profile_id}/"
        "deletion-impact" in paths
    )
    assert (
        "/runtime-provider/v1/providers/{provider_id}/container-profiles/"
        "{profile_id}/deletion-impact" in paths
    )
    assert (
        "/runtime-provider/v1/workspaces/{handle}/runtime-profiles/{profile_id}"
        in paths
    )
    assert (
        "/runtime-provider/v1/providers/{provider_id}/pod-profiles/{profile_id}/"
        "recreation-operations" in paths
    )
    assert (
        "/runtime-provider/v1/providers/{provider_id}/container-profiles/"
        "{profile_id}/recreation-operations" in paths
    )
    assert "/runtime-provider/v1/providers/{provider_id}/recreation-operations" in paths
    assert "/runtime-provider/v1/recreation-operations/{operation_id}" in paths
    assert not any(path.endswith("/contracts/{revision_id}/accept") for path in paths)
    assert (
        "/runtime-provider/v1/providers/{provider_id}/authentication-bindings" in paths
    )
    assert "/runtime-provider/v1/authentication-bindings/{binding_id}" in paths
    assert "/runtime-provider/v1/authentication-bindings/{binding_id}/rotate" in paths
    assert "/runtime-provider/v1/authentication-bindings/{binding_id}/revoke" in paths
    assert (
        "/runtime-provider/v1/authentication-bindings/{binding_id}/audit-events"
        in paths
    )


@pytest.mark.asyncio
async def test_operational_diagnostics_returns_active_snapshot_or_unavailable() -> None:
    """Admin diagnostics expose only bounded active-generation warning evidence."""
    checked_at = datetime.datetime(2026, 8, 12, tzinfo=datetime.UTC)
    diagnostics = RuntimeProviderOperationalDiagnostics(
        checked_at=checked_at,
        warnings=(
            RuntimeProviderOperationalWarning(
                code="rbac_incomplete",
                severity=RuntimeProviderOperationalWarningSeverity.WARNING,
                metadata={
                    "required_verb": "get",
                    "resource_kind": "secrets",
                },
            ),
        ),
    )
    service = create_autospec(RuntimeProviderAdminService, instance=True)
    service.get_operational_diagnostics = AsyncMock(
        return_value=RuntimeProviderOperationalDiagnosticsProjection(
            generation=7,
            protocol_version="agent-runtime-provider-kubernetes-v3",
            diagnostics=diagnostics,
        )
    )

    active = await get_provider_diagnostics(
        service=service,
        provider_id="provider-1",
    )
    service.get_operational_diagnostics.return_value = None
    unavailable = await get_provider_diagnostics(
        service=service,
        provider_id="provider-1",
    )

    assert active.available
    assert active.generation == 7
    assert active.protocol_version == "agent-runtime-provider-kubernetes-v3"
    assert active.checked_at == checked_at
    assert [warning.model_dump(mode="json") for warning in active.warnings] == [
        {
            "code": "rbac_incomplete",
            "severity": "warning",
            "metadata": {
                "required_verb": "get",
                "resource_kind": "secrets",
            },
        }
    ]
    assert unavailable.model_dump(mode="json") == {
        "available": False,
        "generation": None,
        "protocol_version": None,
        "checked_at": None,
        "warnings": [],
    }


def test_admin_mount_protects_binding_routes_with_system_admin() -> None:
    """All binding reads and mutations inherit System Admin protection."""
    binding_routes = [
        route
        for route in _mounted_admin_runtime_provider_routes()
        if "/runtime-provider/v1/" in route.path
        and "authentication-bindings" in route.path
    ]

    assert len(binding_routes) == 6
    for route in binding_routes:
        assert any(
            dependency.dependency is get_system_admin
            for dependency in route.dependencies
        )


def test_admin_mount_protects_all_recreation_routes_with_system_admin() -> None:
    """Every Platform recreation route inherits System Admin protection."""
    recreation_routes = [
        route
        for route in _mounted_admin_runtime_provider_routes()
        if "/runtime-provider/v1/" in route.path
        and "recreation-operations" in route.path
    ]

    assert len(recreation_routes) == 4
    for route in recreation_routes:
        assert any(
            dependency.dependency is get_system_admin
            for dependency in route.dependencies
        )


def test_admin_mount_protects_profile_delete_and_detail_routes() -> None:
    """Profile deletion impact, mutation, and detail inherit System Admin auth."""
    protected_routes = [
        route
        for route in _mounted_admin_runtime_provider_routes()
        if (
            route.path.endswith("/deletion-impact")
            or (
                route.path.endswith("/{profile_id}")
                and "profiles" in route.path
                and route.methods is not None
                and "DELETE" in route.methods
            )
            or "/workspaces/{handle}/runtime-profiles/{profile_id}" in route.path
        )
    ]

    assert len(protected_routes) == 5
    for route in protected_routes:
        assert any(
            dependency.dependency is get_system_admin
            for dependency in route.dependencies
        )


@pytest.mark.asyncio
async def test_delete_profile_forwards_exact_version_and_actor() -> None:
    """Pod Profile deletion forwards exact identity, version, kind, and actor."""
    service = create_autospec(RuntimeProfileAdminService, instance=True)
    service.delete_profile = AsyncMock(
        return_value=RuntimeInfrastructureProfileDeletion(
            profile_id="profile-1",
            superseded_recreation_operation_count=1,
            skipped_recreation_item_count=2,
        )
    )

    response = await delete_pod_profile(
        system_admin=_system_admin(),
        service=service,
        request_body=RuntimeInfrastructureProfileDeleteRequest(
            expected_version=4,
        ),
        provider_id="provider-1",
        profile_id="profile-1",
    )

    assert response.profile_id == "profile-1"
    assert response.superseded_recreation_operation_count == 1
    assert response.skipped_recreation_item_count == 2
    service.delete_profile.assert_awaited_once_with(
        "provider-1",
        "profile-1",
        profile_kind="kubernetes_pod",
        expected_version=4,
        actor_user_id="admin-1",
    )


@pytest.mark.asyncio
async def test_delete_profile_maps_current_reference_conflict() -> None:
    """Current references return a bounded conflict with the authoritative count."""
    service = create_autospec(RuntimeProfileAdminService, instance=True)
    service.delete_profile = AsyncMock(
        side_effect=RuntimeProfileAdminUnavailable(
            code="profile_referenced",
            message="Runtime infrastructure Profile is referenced.",
            blocking_reference_count=3,
        )
    )

    with pytest.raises(HTTPException) as captured:
        await delete_pod_profile(
            system_admin=_system_admin(),
            service=service,
            request_body=RuntimeInfrastructureProfileDeleteRequest(
                expected_version=4,
            ),
            provider_id="provider-1",
            profile_id="profile-1",
        )

    assert captured.value.status_code == 409
    assert captured.value.detail == {
        "code": "profile_referenced",
        "blocking_reference_count": 3,
    }


@pytest.mark.asyncio
async def test_provider_recreation_conflict_returns_current_version() -> None:
    """A stale Provider version returns a bounded optimistic conflict."""
    service = create_autospec(RuntimeRecreationService, instance=True)
    service.create_provider_operation = AsyncMock(
        side_effect=RuntimeRecreationUnavailable(
            code="target_version_conflict",
            message="Runtime Provider version is stale.",
            current_version=5,
        )
    )

    with pytest.raises(HTTPException) as error:
        await create_provider_recreation(
            system_admin=_system_admin(),
            service=service,
            request_body=RuntimeRecreationCreateRequest(
                expected_version=4,
                concurrency_limit=2,
            ),
            provider_id="provider-1",
        )

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "target_version_conflict",
        "current_version": 5,
    }
    service.create_provider_operation.assert_awaited_once_with(
        "provider-1",
        expected_admin_version=4,
        concurrency_limit=2,
        actor_user_id="admin-1",
    )


@pytest.mark.asyncio
async def test_platform_recreation_returns_bounded_paged_details() -> None:
    """Platform progress forwards paging and serializes bounded failures."""
    service = create_autospec(RuntimeRecreationService, instance=True)
    service.get_platform_operation = AsyncMock(
        return_value=RuntimeRecreationProjection(
            operation=_recreation_operation(),
            items=(_recreation_item(),),
        )
    )

    response = await get_platform_recreation(
        service=service,
        operation_id="operation-1",
        offset=2,
        limit=3,
    )

    assert response.id == "operation-1"
    assert response.failed_count == 1
    assert len(response.items) == 1
    assert response.items[0].runtime_id == "runtime-1"
    assert response.items[0].failure_code == "recreation_failed"
    service.get_platform_operation.assert_awaited_once_with(
        "operation-1",
        offset=2,
        limit=3,
    )


@pytest.mark.asyncio
async def test_rotate_returns_secret_once_with_safe_binding_projection() -> None:
    """Only the rotate mutation response includes plaintext enrollment evidence."""
    expires_at = datetime.datetime(2026, 7, 23, 12, tzinfo=datetime.UTC)
    service = create_autospec(RuntimeProviderBindingAdminService, instance=True)
    service.rotate_binding = AsyncMock(
        return_value=RuntimeProviderBindingRotation(
            binding=_projection(admin_version=2),
            grant_id="grant-1",
            secret="one-time-secret",
            expires_at=expires_at,
        )
    )
    response = await rotate_auth_binding(
        system_admin=_system_admin(),
        service=service,
        request_body=RuntimeProviderAuthenticationBindingRotateRequest(
            expected_admin_version=1,
            expires_at=expires_at,
        ),
        binding_id="binding-1",
    )

    assert response.secret == "one-time-secret"
    assert response.grant_id == "grant-1"
    assert response.binding.provider_id == "provider-1"
    assert response.binding.admin_version == 2
    assert "secret" not in response.binding.model_dump(mode="json")
    service.rotate_binding.assert_awaited_once_with(
        "binding-1",
        expected_admin_version=1,
        expires_at=expires_at,
        actor_user_id="admin-1",
    )


def test_rotate_rejects_timezone_naive_expiry() -> None:
    """A timezone-free expiry is rejected before service execution."""
    with pytest.raises(ValidationError):
        RuntimeProviderAuthenticationBindingRotateRequest(
            expected_admin_version=1,
            expires_at=datetime.datetime(2026, 7, 23, 12),
        )


@pytest.mark.parametrize(
    ("code", "expected_status"),
    (
        ("provider_not_found", 404),
        ("binding_not_found", 404),
        ("binding_config_invalid", 422),
        ("binding_subject_invalid", 422),
        ("grant_expiry_invalid", 422),
        ("binding_read_only", 409),
        ("binding_not_active", 409),
        ("unsupported_binding_method", 409),
        ("provider_unavailable", 409),
    ),
)
@pytest.mark.asyncio
async def test_binding_failures_map_to_bounded_admin_errors(
    code: str,
    expected_status: int,
) -> None:
    """Known lifecycle failures map to bounded non-secret HTTP responses."""
    service = create_autospec(RuntimeProviderBindingAdminService, instance=True)
    service.get_binding = AsyncMock(
        side_effect=RuntimeProviderBindingAdminUnavailable(code)
    )

    with pytest.raises(HTTPException) as error:
        await get_auth_binding(service=service, binding_id="binding-1")
    assert error.value.status_code == expected_status
    assert error.value.detail == {"code": code}


@pytest.mark.asyncio
async def test_stale_conflict_includes_only_current_safe_binding() -> None:
    """Optimistic conflict returns the current projection without evidence."""
    projection = _projection(admin_version=7)
    service = create_autospec(RuntimeProviderBindingAdminService, instance=True)
    service.get_binding = AsyncMock(
        side_effect=RuntimeProviderBindingAdminUnavailable(
            "stale_binding_version",
            current_binding=projection,
        )
    )
    with pytest.raises(HTTPException) as error:
        await get_auth_binding(service=service, binding_id="binding-1")

    assert error.value.status_code == 409
    assert error.value.detail == {
        "code": "stale_binding_version",
        "current_binding": (
            RuntimeProviderAuthenticationBindingResponse.convert_from(
                projection
            ).model_dump(mode="json")
        ),
    }
