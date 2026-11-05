"""Real route mounting, resolver/issuer separation and secret-safe responses."""

from unittest.mock import AsyncMock

import pytest
from azents_llm_contract.authority import IssuedToken, ModelListResponse, TargetBinding
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from kubernetes_asyncio.client import AuthenticationV1Api
from kubernetes_asyncio.client.models.v1_token_review import V1TokenReview
from kubernetes_asyncio.client.models.v1_token_review_spec import V1TokenReviewSpec
from kubernetes_asyncio.client.models.v1_token_review_status import V1TokenReviewStatus
from kubernetes_asyncio.client.models.v1_user_info import V1UserInfo
from kubernetes_asyncio.client.rest import ApiException
from pydantic import SecretStr

from azents.api import admin, internal
from azents.api.internal.llm import get_kubernetes_resolver_auth
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
from azents.services.llm_resolver_auth import RESOLVER_AUDIENCE, KubernetesResolverAuth
from azents.utils.fastapi.route import as_route_mounter

KEY = "dedicated-resolver-service-secret-32-bytes"
SUBJECT = "system:serviceaccount:azents:azents-llm-proxy"


@pytest.mark.parametrize(
    ("authenticated", "subject", "audiences", "expected"),
    [
        (True, SUBJECT, [RESOLVER_AUDIENCE], 200),
        (False, SUBJECT, [RESOLVER_AUDIENCE], 403),
        (
            True,
            "system:serviceaccount:other:azents-llm-proxy",
            [RESOLVER_AUDIENCE],
            403,
        ),
        (True, "system:serviceaccount:azents:other", [RESOLVER_AUDIENCE], 403),
        (True, SUBJECT, ["azents-runtime-control"], 403),
        (True, SUBJECT, [], 403),
    ],
)
def test_kubernetes_identity_before_agent_lookup(
    service: AsyncMock,
    authenticated: bool,
    subject: str,
    audiences: list[str],
    expected: int,
) -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    api.create_token_review = AsyncMock(
        return_value=V1TokenReview(
            spec=V1TokenReviewSpec(token=KEY, audiences=[RESOLVER_AUDIENCE]),
            status=V1TokenReviewStatus(
                authenticated=authenticated,
                audiences=audiences,
                user=V1UserInfo(username=subject),
            ),
        )
    )
    app = FastAPI()
    internal.mount(as_route_mounter(app))
    app.dependency_overrides[get_config] = lambda: Config.model_construct(
        llm_resolver_service_key=SecretStr(KEY),
        llm_resolver_kubernetes_service_account=SUBJECT,
    )
    app.dependency_overrides[get_kubernetes_resolver_auth] = lambda: (
        KubernetesResolverAuth(api, SUBJECT)
    )
    app.dependency_overrides[LLMAuthorityService] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/llm/models",
        headers={"X-Azents-LLM-Resolver": KEY},
        json={"agent_token": "agent-token"},
    )
    assert response.status_code == expected
    review = api.create_token_review.call_args.args[0]
    assert review.spec.audiences == [RESOLVER_AUDIENCE]
    assert review.spec.token == KEY
    assert api.create_token_review.call_args.kwargs["_request_timeout"] == 10
    if expected == 403:
        service.list_models.assert_not_called()
    else:
        service.list_models.assert_awaited_once()


async def test_kubernetes_review_failure_is_sanitized_and_never_falls_back() -> None:
    api = AsyncMock(spec=AuthenticationV1Api)
    api.create_token_review = AsyncMock(
        side_effect=ApiException(status=500, reason="credential-sentinel")
    )
    with pytest.raises(RuntimeError, match="verification is unavailable") as error:
        await KubernetesResolverAuth(api, SUBJECT).accepts(KEY)
    assert "credential-sentinel" not in str(error.value)
    assert error.value.__suppress_context__


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
