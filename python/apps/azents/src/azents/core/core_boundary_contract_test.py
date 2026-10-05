"""Focused immutable-result and finite-boundary contracts."""

import base64
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import patch

import httpx2 as httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp.types import ListToolsResult
from mcp.types import Tool as McpBaseTool

from azents.core import mcp_transport, oauth2
from azents.core.runtime_profile import (
    DockerContainerResources,
    KubernetesContainerResources,
    KubernetesDinDModule,
    RuntimeProfileNumericConstraintPath,
    RuntimeProfileStringConstraintPath,
    _constraint_paths_for_kind,
    _profile_value_at_path,
)
from azents.core.runtime_profile_test import (
    _docker_spec_v2,
    _kubernetes_spec,
    _kubernetes_spec_v2,
)


@pytest.mark.parametrize("error", [RuntimeError("unexpected"), ValueError("bug")])
def test_state_runtime_failures_propagate(error: Exception) -> None:
    """Only malformed state failures are converted to rejection."""
    state = oauth2.create_oauth_state("toolkit", "user", "key")
    with patch("azents.core.oauth2.AESGCM", side_effect=error):
        with pytest.raises(type(error), match=str(error)):
            oauth2.verify_oauth_state(state, "key")


@pytest.mark.parametrize("plaintext", [b"not-json", b"\xff", b"[]"])
def test_authenticated_malformed_payload_is_rejected(plaintext: bytes) -> None:
    """Authenticated bytes still require valid object JSON."""
    iv = bytes(range(12))
    key = hashlib.sha256(b"key").digest()
    encrypted = AESGCM(key).encrypt(iv, plaintext, None)
    state = base64.urlsafe_b64encode(iv + encrypted).decode("ascii")
    assert oauth2.verify_oauth_state(state, "key") is None


def test_named_pkce_and_toolkit_state_fields() -> None:
    """Same-type fields retain explicit protocol meanings."""
    pkce = oauth2.generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(
            hashlib.sha256(pkce.code_verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert pkce.code_challenge == expected
    state = oauth2.create_toolkit_oauth_state(
        toolkit_id="toolkit",
        workspace_id="workspace",
        user_id="user",
        redirect_uri="https://app.test/callback",
        code_verifier=pkce.code_verifier,
        secret_key="key",
    )
    verified = oauth2.verify_toolkit_oauth_state(state, "key")
    assert verified is not None
    assert verified.toolkit_id == "toolkit"
    assert verified.workspace_id == "workspace"
    assert verified.user_id == "user"
    assert verified.redirect_uri == "https://app.test/callback"
    assert verified.code_verifier == pkce.code_verifier


@pytest.mark.parametrize("fallback", [False, True])
async def test_named_mcp_discovery_transport(fallback: bool) -> None:
    """Discovery keeps its tools and Streamable HTTP/SSE selection."""
    tool = McpBaseTool(name="tool", input_schema={"type": "object"})
    selected: list[bool] = []

    class Session:
        async def list_tools(self) -> ListToolsResult:
            return ListToolsResult(tools=[tool])

    @asynccontextmanager
    async def session(
        _url: str,
        _headers: dict[str, str],
        _timeout: float,
        use_streamable_http: bool = False,
        *,
        proxy_url: str | None = None,
        auth: httpx.Auth | None = None,
    ) -> AsyncIterator[Session]:
        selected.append(use_streamable_http)
        if fallback and use_streamable_http:
            response = httpx.Response(
                405, request=httpx.Request("POST", "https://mcp.test")
            )
            response.raise_for_status()
        yield Session()

    with patch("azents.core.mcp_transport._mcp_session", side_effect=session):
        result = await mcp_transport.list_tools("https://mcp.test", {}, 5)
    assert result.tools == [tool]
    assert result.use_streamable_http is not fallback
    assert selected == ([True, False] if fallback else [True])


@pytest.mark.parametrize("version", [1, 2])
def test_all_kubernetes_constraint_paths_are_typed(version: int) -> None:
    """Every finite Pod constraint selects the same declared model field."""
    resources = KubernetesContainerResources(
        cpu_request_millicores=11,
        cpu_limit_millicores=12,
        memory_request_bytes=13,
        memory_limit_bytes=14,
    )
    spec = (_kubernetes_spec() if version == 1 else _kubernetes_spec_v2()).model_copy(
        update={
            "runner_resources": resources,
            "dind": KubernetesDinDModule(
                engine_resources=resources,
                docker_storage_bytes=15,
                shared_temporary_storage_bytes=16,
            ),
            "service_account_name": "runner",
        }
    )
    paths = _constraint_paths_for_kind(spec.profile_kind)
    expected = {
        RuntimeProfileNumericConstraintPath.RUNNER_CPU_REQUEST: 11,
        RuntimeProfileNumericConstraintPath.RUNNER_CPU_LIMIT: 12,
        RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_REQUEST: 13,
        RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_LIMIT: 14,
        RuntimeProfileNumericConstraintPath.WORKSPACE_STORAGE: 1,
        RuntimeProfileNumericConstraintPath.DIND_ENGINE_CPU_REQUEST: 11,
        RuntimeProfileNumericConstraintPath.DIND_ENGINE_CPU_LIMIT: 12,
        RuntimeProfileNumericConstraintPath.DIND_ENGINE_MEMORY_REQUEST: 13,
        RuntimeProfileNumericConstraintPath.DIND_ENGINE_MEMORY_LIMIT: 14,
        RuntimeProfileNumericConstraintPath.DIND_DOCKER_STORAGE: 15,
        RuntimeProfileNumericConstraintPath.DIND_SHARED_TEMPORARY_STORAGE: 16,
    }
    assert set(expected) == paths.numeric
    for path, value in expected.items():
        assert _profile_value_at_path(spec, path) == value
        if path.value.startswith("dind."):
            assert (
                _profile_value_at_path(spec.model_copy(update={"dind": None}), path)
                is None
            )
    assert (
        _profile_value_at_path(
            spec, RuntimeProfileStringConstraintPath.WORKSPACE_STORAGE_CLASS
        )
        == "standard"
    )
    assert (
        _profile_value_at_path(spec, RuntimeProfileStringConstraintPath.SERVICE_ACCOUNT)
        == "runner"
    )


def test_all_docker_constraint_paths_are_typed() -> None:
    """Docker reservation and limit meanings remain provider-specific."""
    spec = _docker_spec_v2().model_copy(
        update={
            "runner_resources": DockerContainerResources(
                cpu_reservation_millicores=21,
                cpu_limit_millicores=22,
                memory_reservation_bytes=23,
                memory_limit_bytes=24,
            ),
            "network_name": "network",
        }
    )
    paths = _constraint_paths_for_kind(spec.profile_kind)
    expected = {
        RuntimeProfileNumericConstraintPath.RUNNER_CPU_RESERVATION: 21,
        RuntimeProfileNumericConstraintPath.RUNNER_CPU_LIMIT: 22,
        RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_RESERVATION: 23,
        RuntimeProfileNumericConstraintPath.RUNNER_MEMORY_LIMIT: 24,
    }
    assert set(expected) == paths.numeric
    for path, value in expected.items():
        assert _profile_value_at_path(spec, path) == value
    assert (
        _profile_value_at_path(spec, RuntimeProfileStringConstraintPath.DOCKER_NETWORK)
        == "network"
    )
