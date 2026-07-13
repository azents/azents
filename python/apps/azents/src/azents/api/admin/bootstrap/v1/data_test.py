"""Tests for system bootstrap Admin API response conversion."""

from azents.services.system_bootstrap.data import (
    SystemBootstrapOutput,
    SystemBootstrapStatusOutput,
)

from .data import (
    SystemBootstrapFirstAdminResponse,
    SystemBootstrapStatusResponse,
)


def test_convert_bootstrap_status_service_output() -> None:
    response = SystemBootstrapStatusResponse.convert_from(
        SystemBootstrapStatusOutput(available=True)
    )

    assert response == SystemBootstrapStatusResponse(available=True)


def test_convert_first_admin_service_output() -> None:
    response = SystemBootstrapFirstAdminResponse.convert_from(
        SystemBootstrapOutput(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=300,
        )
    )

    assert response == SystemBootstrapFirstAdminResponse(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_in=300,
    )
