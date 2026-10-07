"""Public login capability lookup contract tests."""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI

from azents.api.public.auth.v1 import router
from azents.services.auth import AuthService
from azents.services.auth.data import LoginMethodsInput, LoginMethodsOutput


@pytest.mark.parametrize("email", [None, "user@example.com"])
@pytest.mark.parametrize("email_available", [False, True])
async def test_login_methods_optional_email(
    email: str | None, email_available: bool
) -> None:
    """Omitting email exposes instance availability; email queries still work."""
    service = Mock(spec=AuthService)
    lookup = AsyncMock(
        return_value=LoginMethodsOutput(
            has_password=email is not None,
            email_available=email_available,
        )
    )
    service.get_login_methods = lookup
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[AuthService] = lambda: service

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/login/methods", params={"email": email} if email is not None else {}
        )

    assert response.status_code == 200
    assert response.json() == {
        "has_password": email is not None,
        "email_available": email_available,
    }
    lookup.assert_awaited_once_with(LoginMethodsInput(email=email))
