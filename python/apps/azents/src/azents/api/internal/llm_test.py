"""Real route mounting, resolver/issuer separation and secret-safe responses."""

from unittest.mock import AsyncMock

import pytest
from azents_llm_contract.authority import IssuedToken, ModelListResponse, TargetBinding
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from azents.api import admin, internal
from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.config import Config
from azents.core.deps import get_config
from azents.services.llm_access import LLMAccessService
from azents.services.llm_authority import (
    LLMAuthorityService,
    project_configuration,
    project_credential,
)
from azents.services.llm_authority_test import NOW, SENTINEL, prepared
from azents.utils.fastapi.route import as_route_mounter

KEY = "dedicated-resolver-service-secret-32-bytes"


@pytest.fixture
def service() -> AsyncMock:
    value = prepared()
    service = AsyncMock(spec=LLMAuthorityService)
    service.list_models.return_value = ModelListResponse(
        identity=value.identity, models=("model",)
    )
    service.resolve.return_value = TargetBinding(
        identity=value.identity,
        integration_id="integration",
        target_id="a" * 64,
        public_model="model",
        model_identifier="model",
        configuration=project_configuration(value),
        credential=project_credential(value.integration),
    )
    return service


@pytest.fixture
def client(service: AsyncMock) -> TestClient:
    app = FastAPI()
    internal.mount(as_route_mounter(app))
    app.dependency_overrides[get_config] = lambda: Config.model_construct(
        llm_resolver_service_key=SecretStr(KEY)
    )
    app.dependency_overrides[LLMAuthorityService] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize("header", [None, "wrong", "agent-token"])
def test_service_auth_fails_before_agent_lookup(
    client: TestClient, service: AsyncMock, header: str | None
) -> None:
    response = client.post(
        "/llm/models",
        headers={} if header is None else {"X-Azents-LLM-Resolver": header},
        json={"agent_token": "agent-token"},
    )
    assert response.status_code == 403
    service.list_models.assert_not_called()


def test_valid_resolver_list_has_no_credentials_or_targets(
    client: TestClient, service: AsyncMock
) -> None:
    response = client.post(
        "/llm/models",
        headers={"X-Azents-LLM-Resolver": KEY},
        json={"agent_token": "agent-token"},
    )
    assert response.status_code == 200
    assert response.json()["models"] == ["model"]
    assert "target_id" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    service.list_models.assert_awaited_once_with(agent_token="agent-token")


def test_binding_uses_explicit_protected_wire_serialization(client: TestClient) -> None:
    response = client.post(
        "/llm/resolve",
        headers={"X-Azents-LLM-Resolver": KEY},
        json={"agent_token": "agent-token", "model": "model", "target_id": "a" * 64},
    )
    assert response.status_code == 200
    assert response.json()["credential"]["api_key"] == SENTINEL
    assert response.headers["Cache-Control"] == "no-store"
    assert "agent-token" not in response.text and KEY not in response.text


@pytest.mark.parametrize(
    "extra", ["refresh_token", "credentials", "integration_id", "api_base"]
)
def test_unknown_fields_do_not_echo_secret_inputs(
    client: TestClient, extra: str
) -> None:
    response = client.post(
        "/llm/resolve",
        headers={"X-Azents-LLM-Resolver": KEY},
        json={
            "agent_token": "agent-token",
            "model": "model",
            "target_id": "a" * 64,
            extra: SENTINEL,
        },
    )
    assert response.status_code == 422
    assert SENTINEL not in response.text and "agent-token" not in response.text
    assert response.headers["Cache-Control"] == "no-store"


def test_resolver_has_no_issuer_routes(client: TestClient) -> None:
    assert (
        client.post(
            "/llm/supplies", headers={"X-Azents-LLM-Resolver": KEY}, json={}
        ).status_code
        == 404
    )


def test_actual_admin_mount_rejects_resolver_identity() -> None:
    app = FastAPI()
    admin.mount(as_route_mounter(app))

    async def deny_admin() -> SystemAdmin:
        raise HTTPException(
            status_code=403, detail="System administrator access required"
        )

    app.dependency_overrides[get_system_admin] = deny_admin
    service = AsyncMock(spec=LLMAccessService)
    app.dependency_overrides[LLMAccessService] = lambda: service
    response = TestClient(app).post(
        "/llm-access/v1/supplies",
        headers={"X-Azents-LLM-Resolver": KEY},
        json={"agent_id": "agent", "supply_subject": "development"},
    )
    assert response.status_code == 403
    service.issue.assert_not_called()


def test_admin_issuance_returns_token_only_in_creation_response() -> None:
    app = FastAPI()
    admin.mount(as_route_mounter(app))
    app.dependency_overrides[get_system_admin] = lambda: SystemAdmin(
        user_id="admin", session_id="session", elevated=True
    )
    service = AsyncMock(spec=LLMAccessService)
    service.issue.return_value = IssuedToken(
        supply_id="supply",
        token_id="token",
        agent_token=SecretStr(SENTINEL),
        expires_at=NOW,
        predecessor_expires_at=None,
    )
    app.dependency_overrides[LLMAccessService] = lambda: service
    response = TestClient(app).post(
        "/llm-access/v1/supplies",
        json={"agent_id": "agent", "supply_subject": "development"},
    )
    assert response.status_code == 201
    assert response.json()["agent_token"] == SENTINEL
    assert response.headers["Cache-Control"] == "no-store"
    service.issue.assert_awaited_once_with(
        agent_id="agent", subject="development", issuer="system-admin:admin"
    )
