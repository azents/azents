"""Runtime Provider inventory and authentication v1 Admin API tests."""

import datetime
from unittest.mock import AsyncMock, create_autospec

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from azents.api.admin import mount as mount_admin
from azents.api.admin.runtime_provider.v1 import (
    get_auth_binding,
    mount,
    rotate_auth_binding,
)
from azents.api.admin.runtime_provider.v1.data import (
    RuntimeProviderAuthenticationBindingResponse,
    RuntimeProviderAuthenticationBindingRotateRequest,
)
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
)
from azents.repos.runtime_provider_binding.data import RuntimeProviderAuthBinding
from azents.services.runtime_provider_binding_admin.service import (
    RuntimeProviderBindingAdminProjection,
    RuntimeProviderBindingAdminService,
    RuntimeProviderBindingAdminUnavailable,
    RuntimeProviderBindingRotation,
)
from azents.utils.fastapi.route import as_route_mounter


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


def test_mounts_runtime_provider_inventory_and_authentication_routes() -> None:
    """Expose Provider inventory, policy, availability, and binding routes."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert "/runtime-provider/v1/providers" in paths
    assert "/runtime-provider/v1/providers/{provider_id}" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/policy" in paths
    assert "/runtime-provider/v1/providers/{provider_id}/availability" in paths
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


def test_admin_mount_protects_binding_routes_with_system_admin() -> None:
    """All binding reads and mutations inherit System Admin protection."""
    app = FastAPI()
    mount_admin(as_route_mounter(app))
    binding_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and "/runtime-provider/v1/" in route.path
        and "authentication-bindings" in route.path
    ]

    assert len(binding_routes) == 6
    for route in binding_routes:
        assert any(
            dependency.call is get_system_admin
            for dependency in route.dependant.dependencies
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
