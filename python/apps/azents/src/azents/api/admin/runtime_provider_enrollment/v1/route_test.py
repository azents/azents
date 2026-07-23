"""Runtime Provider enrollment v1 Admin API tests."""

import datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute

from azents.api.admin.runtime_provider_enrollment.v1 import (
    issue_enrollment_grant,
    mount,
    revoke_credential,
)
from azents.api.admin.runtime_provider_enrollment.v1.data import (
    RuntimeProviderEnrollmentGrantIssueRequest,
)
from azents.core.auth.deps import SystemAdmin
from azents.services.runtime_provider_control.data import (
    RuntimeProviderEnrollmentGrantIssued,
    RuntimeProviderEnrollmentUnavailable,
)
from azents.utils.fastapi.route import as_route_mounter


class FakeEnrollmentService:
    """Return configured control-plane outcomes for route tests."""

    def __init__(
        self,
        *,
        issued: RuntimeProviderEnrollmentGrantIssued | None,
        revoked: bool,
    ) -> None:
        self.issued = issued
        self.revoked = revoked

    async def issue_grant(
        self,
        *,
        provider_id: str,
        expires_at: datetime.datetime,
        issued_by_user_id: str | None,
        issued_by_source_id: str | None,
    ) -> RuntimeProviderEnrollmentGrantIssued:
        """Issue a fixed grant or report an unavailable Provider."""
        assert provider_id == "provider-1"
        assert issued_by_user_id == "admin-1"
        assert issued_by_source_id is None
        if self.issued is None:
            raise RuntimeProviderEnrollmentUnavailable("provider_unavailable")
        assert expires_at == self.issued.expires_at
        return self.issued

    async def revoke_credential(
        self,
        *,
        credential_id: str,
        revoked_by_user_id: str | None,
    ) -> bool:
        """Return a fixed credential revocation result."""
        assert credential_id == "credential-1"
        assert revoked_by_user_id == "admin-1"
        return self.revoked


def _system_admin() -> SystemAdmin:
    """Create one authenticated System Admin context."""
    return SystemAdmin(user_id="admin-1", session_id="session-1")


def test_mounts_provider_enrollment_control_plane_routes() -> None:
    """Expose issuance and revoke routes under the protected Admin prefix."""
    app = FastAPI()
    mount(as_route_mounter(app))

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert (
        "/runtime-provider-enrollment/v1/runtime-providers/"
        "{provider_id}/enrollment-grants"
    ) in paths
    assert (
        "/runtime-provider-enrollment/v1/runtime-provider-credentials/{credential_id}"
    ) in paths


@pytest.mark.asyncio
async def test_issue_grant_returns_one_time_operator_secret() -> None:
    """Return plaintext enrollment material only in the issuance response."""
    expires_at = datetime.datetime(2026, 7, 23, tzinfo=datetime.UTC)
    response = await issue_enrollment_grant(
        system_admin=_system_admin(),
        service=FakeEnrollmentService(
            issued=RuntimeProviderEnrollmentGrantIssued(
                grant_id="grant-1",
                provider_id="provider-1",
                secret="grant-secret",
                expires_at=expires_at,
            ),
            revoked=True,
        ),
        request_body=RuntimeProviderEnrollmentGrantIssueRequest(expires_at=expires_at),
        provider_id="provider-1",
    )

    assert response.grant_id == "grant-1"
    assert response.secret == "grant-secret"


@pytest.mark.asyncio
async def test_revoke_unknown_credential_returns_not_found() -> None:
    """Do not represent absent credentials as successful revocation."""
    with pytest.raises(HTTPException) as error:
        await revoke_credential(
            system_admin=_system_admin(),
            service=FakeEnrollmentService(issued=None, revoked=False),
            credential_id="credential-1",
        )

    assert error.value.status_code == 404
