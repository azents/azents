"""Kubernetes Toolkit tests."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from kubernetes_asyncio.client.rest import ApiException
from lightkube import ApiError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    ClusterConfig,
    KubernetesToolkitConfig,
    ResolveContext,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.kubernetes import (
    K8sApplyInput,
    K8sDeleteInput,
    K8sExecInput,
    KubernetesToolkit,
    KubernetesToolkitProvider,
    check_access,
    resolve_namespace,
)
from azents.engine.tools.kubernetes_auth import (
    EksCredential,
    GkeCredential,
    KubernetesCredentials,
    TokenCredential,
    validate_kubeconfig,
)
from azents.engine.tools.kubernetes_discovery import ResourceDiscoveryCache

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id="user-1",
        workspace_id="ws-1",
        model="test-model",
        run_id="run-1",
        publish_event=AsyncMock(),
    )


def _make_resolve_context(credentials_json: str) -> ResolveContext:
    """Create ResolveContext for tests."""
    return ResolveContext(
        toolkit_id="toolkit-1",
        toolkit_name="Kubernetes",
        credentials_json=credentials_json,
        agent_id="agent-1",
        session_id="session-1",
        user_id="user-1",
        session=AsyncMock(spec=AsyncSession),
        web_url="https://test.example.com",
        oauth_secret_key="test-key",
        workspace_id="ws-1",
        workspace_handle="ws",
    )


# ---------------------------------------------------------------------------
# KubernetesToolkitConfig tests
# ---------------------------------------------------------------------------


class TestKubernetesToolkitConfig:
    """Validate config defaults."""

    def test_defaults(self) -> None:
        """Check that defaults are correct."""
        config = KubernetesToolkitConfig(
            clusters=[
                ClusterConfig(name="test", auth_type="token"),
            ],
        )
        assert config.read_only is True
        assert config.denied_kinds == ["Secret"]
        assert config.allowed_namespaces is None
        assert config.timeout == 30.0

    def test_custom_values(self) -> None:
        """Check that custom values can be set."""
        config = KubernetesToolkitConfig(
            clusters=[
                ClusterConfig(name="prod", auth_type="kubeconfig"),
            ],
            read_only=False,
            allowed_namespaces=["app", "monitoring"],
            denied_kinds=["Secret", "ConfigMap"],
            timeout=60.0,
        )
        assert config.read_only is False
        assert config.allowed_namespaces == ["app", "monitoring"]
        assert config.denied_kinds == ["Secret", "ConfigMap"]
        assert config.timeout == 60.0


# ---------------------------------------------------------------------------
# ClusterConfig tests
# ---------------------------------------------------------------------------


class TestClusterConfig:
    """ClusterConfig field validation."""

    def test_minimal_config(self) -> None:
        """Check that creation is possible with only minimum required fields."""
        cluster = ClusterConfig(name="prod", auth_type="token")
        assert cluster.name == "prod"
        assert cluster.auth_type == "token"
        assert cluster.default_namespace == "default"
        assert cluster.context is None
        assert cluster.api_server is None
        assert cluster.cluster_name is None
        assert cluster.region is None
        assert cluster.project_id is None

    def test_kubeconfig_fields(self) -> None:
        """Check that context field can be set for kubeconfig authentication."""
        cluster = ClusterConfig(
            name="dev",
            auth_type="kubeconfig",
            context="dev-context",
            default_namespace="dev-ns",
        )
        assert cluster.auth_type == "kubeconfig"
        assert cluster.context == "dev-context"
        assert cluster.default_namespace == "dev-ns"

    def test_token_fields(self) -> None:
        """Check that api_server field can be set for token authentication."""
        cluster = ClusterConfig(
            name="staging",
            auth_type="token",
            api_server="https://k8s.example.com:6443",
        )
        assert cluster.api_server == "https://k8s.example.com:6443"

    def test_eks_fields(self) -> None:
        """Check that cluster_name, region fields can be set for EKS authentication."""
        cluster = ClusterConfig(
            name="eks-prod",
            auth_type="eks",
            cluster_name="my-cluster",
            region="ap-northeast-2",
        )
        assert cluster.cluster_name == "my-cluster"
        assert cluster.region == "ap-northeast-2"

    def test_gke_fields(self) -> None:
        """Check that GKE authentication fields can be set."""
        cluster = ClusterConfig(
            name="gke-prod",
            auth_type="gke",
            cluster_name="my-gke-cluster",
            region="asia-northeast3",
            project_id="my-project",
        )
        assert cluster.project_id == "my-project"


# ---------------------------------------------------------------------------
# _check_access tests
# ---------------------------------------------------------------------------


class TestCheckAccess:
    """check_access() security validation tests."""

    def test_denied_kind(self) -> None:
        """Kind included in denied_kinds is denied."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            denied_kinds=["Secret", "ConfigMap"],
        )
        with pytest.raises(FunctionToolError, match="Access denied.*Secret"):
            check_access(config, "Secret", "default")

    def test_denied_kind_configmap(self) -> None:
        """Denied when ConfigMap is included in denied_kinds."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            denied_kinds=["Secret", "ConfigMap"],
        )
        with pytest.raises(FunctionToolError, match="Access denied.*ConfigMap"):
            check_access(config, "ConfigMap", "default")

    def test_allowed_kind(self) -> None:
        """Kind not included in denied_kinds is allowed."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            denied_kinds=["Secret"],
        )
        # Pass if no exception is raised
        check_access(config, "Pod", "default")

    def test_denied_namespace(self) -> None:
        """Namespace not included in allowed_namespaces is denied."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            allowed_namespaces=["app", "monitoring"],
        )
        with pytest.raises(FunctionToolError, match="Access denied.*namespace"):
            check_access(config, "Pod", "kube-system")

    def test_allowed_namespace(self) -> None:
        """Namespace included in allowed_namespaces is allowed."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            allowed_namespaces=["app", "monitoring"],
        )
        check_access(config, "Pod", "app")

    def test_no_namespace_restriction(self) -> None:
        """When allowed_namespaces is None, all namespaces are allowed."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            allowed_namespaces=None,
        )
        check_access(config, "Pod", "any-namespace")

    def test_namespace_none_with_allowed(self) -> None:
        """Skip allowed_namespaces check when namespace is None."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="t", auth_type="token")],
            allowed_namespaces=["app"],
        )
        check_access(config, "Pod", None)


# ---------------------------------------------------------------------------
# _resolve_namespace tests
# ---------------------------------------------------------------------------


class TestResolveNamespace:
    """resolve_namespace() tests."""

    def test_explicit_namespace(self) -> None:
        """Use explicit namespace as-is when specified."""
        cluster_config = ClusterConfig(
            name="t", auth_type="token", default_namespace="default"
        )
        assert resolve_namespace(cluster_config, "custom") == "custom"

    def test_default_namespace(self) -> None:
        """Use default_namespace when namespace is None."""
        cluster_config = ClusterConfig(
            name="t", auth_type="token", default_namespace="my-default"
        )
        assert resolve_namespace(cluster_config, None) == "my-default"


# ---------------------------------------------------------------------------
# validate_kubeconfig tests
# ---------------------------------------------------------------------------


class TestValidateKubeconfig:
    """kubeconfig exec provider rejection tests."""

    def test_exec_provider_rejected(self) -> None:
        """kubeconfig containing exec provider is rejected."""
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "users": [
                {
                    "name": "user1",
                    "user": {
                        "exec": {
                            "command": "aws",
                            "args": ["eks", "get-token"],
                        },
                    },
                },
            ],
        }
        with pytest.raises(ValueError, match="exec provider"):
            validate_kubeconfig(kubeconfig)

    def test_token_auth_allowed(self) -> None:
        """kubeconfig with token-based authentication is allowed."""
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "users": [
                {
                    "name": "user1",
                    "user": {
                        "token": "my-token",
                    },
                },
            ],
        }
        # Pass if no exception is raised
        validate_kubeconfig(kubeconfig)

    def test_empty_users(self) -> None:
        """kubeconfig with empty users is allowed."""
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "users": [],
        }
        validate_kubeconfig(kubeconfig)

    def test_no_users_key(self) -> None:
        """kubeconfig without users key is allowed."""
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
        }
        validate_kubeconfig(kubeconfig)

    def test_client_certificate_allowed(self) -> None:
        """client-certificate-data based authentication is allowed."""
        kubeconfig = {
            "apiVersion": "v1",
            "kind": "Config",
            "users": [
                {
                    "name": "user1",
                    "user": {
                        "client-certificate-data": "base64cert",
                        "client-key-data": "base64key",
                    },
                },
            ],
        }
        validate_kubeconfig(kubeconfig)


# ---------------------------------------------------------------------------
# EKS/GKE Credential model tests
# ---------------------------------------------------------------------------


class TestEksCredential:
    """EksCredential model tests."""

    def test_basic_fields(self) -> None:
        """Check that creation is possible with only required fields."""
        cred = EksCredential(
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret...",
        )
        assert cred.type == "eks"
        assert cred.aws_access_key_id == "AKIA..."
        assert cred.aws_secret_access_key == "secret..."
        assert cred.role_arn is None

    def test_with_role_arn(self) -> None:
        """Check creation including role_arn."""
        cred = EksCredential(
            aws_access_key_id="AKIA...",
            aws_secret_access_key="secret...",
            role_arn="arn:aws:iam::123456789012:role/my-role",
        )
        assert cred.role_arn == "arn:aws:iam::123456789012:role/my-role"


class TestGkeCredential:
    """GkeCredential model tests."""

    def test_basic_fields(self) -> None:
        """Check that creation is possible with Service Account key JSON."""
        sa_key: dict[str, object] = {
            "type": "service_account",
            "project_id": "my-project",
            "private_key_id": "key-id",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
            "client_email": "sa@my-project.iam.gserviceaccount.com",
        }
        cred = GkeCredential(service_account_key=sa_key)
        assert cred.type == "gke"
        assert cred.service_account_key["project_id"] == "my-project"


class TestKubernetesCredentialsWithCloud:
    """Tests parsing EKS/GKE credential from KubernetesCredentials."""

    def test_parse_eks_credential(self) -> None:
        """Check that EKS credential is parsed correctly as discriminated union."""
        data = {
            "clusters": {
                "eks-prod": {
                    "type": "eks",
                    "aws_access_key_id": "AKIA...",
                    "aws_secret_access_key": "secret...",
                }
            }
        }
        creds = KubernetesCredentials.model_validate(data)
        eks_cred = creds.clusters["eks-prod"]
        assert isinstance(eks_cred, EksCredential)
        assert eks_cred.aws_access_key_id == "AKIA..."

    def test_parse_gke_credential(self) -> None:
        """Check that GKE credential is parsed correctly as discriminated union."""
        data = {
            "clusters": {
                "gke-prod": {
                    "type": "gke",
                    "service_account_key": {
                        "type": "service_account",
                        "project_id": "my-project",
                    },
                }
            }
        }
        creds = KubernetesCredentials.model_validate(data)
        gke_cred = creds.clusters["gke-prod"]
        assert isinstance(gke_cred, GkeCredential)
        assert gke_cred.service_account_key["project_id"] == "my-project"

    def test_parse_mixed_credentials(self) -> None:
        """Check that multiple credential types can be parsed at once."""
        data = {
            "clusters": {
                "eks-prod": {
                    "type": "eks",
                    "aws_access_key_id": "AKIA...",
                    "aws_secret_access_key": "secret...",
                },
                "gke-prod": {
                    "type": "gke",
                    "service_account_key": {"type": "service_account"},
                },
                "manual": {
                    "type": "token",
                    "token": "my-token",
                },
            }
        }
        creds = KubernetesCredentials.model_validate(data)
        assert isinstance(creds.clusters["eks-prod"], EksCredential)
        assert isinstance(creds.clusters["gke-prod"], GkeCredential)


# ---------------------------------------------------------------------------
# KubernetesToolkitProvider tests
# ---------------------------------------------------------------------------


class TestKubernetesToolkitProvider:
    """KubernetesToolkitProvider default property tests."""

    def test_slug(self) -> None:
        """Check that slug is 'kubernetes'."""
        assert KubernetesToolkitProvider.slug == "kubernetes"

    def test_config_model(self) -> None:
        """Check that config_model is KubernetesToolkitConfig."""
        assert KubernetesToolkitProvider.config_model is KubernetesToolkitConfig


# ---------------------------------------------------------------------------
# KubernetesToolkitProvider.test_connection tests
# ---------------------------------------------------------------------------


class TestKubernetesToolkitProviderTestConnection:
    """KubernetesToolkitProvider.test_connection() tests."""

    def _make_config(
        self,
        clusters: list[ClusterConfig] | None = None,
    ) -> KubernetesToolkitConfig:
        """Create KubernetesToolkitConfig for tests."""
        if clusters is None:
            clusters = [
                ClusterConfig(
                    name="prod",
                    auth_type="token",
                    api_server="https://k8s.example.com:6443",
                ),
            ]
        return KubernetesToolkitConfig(clusters=clusters)

    def _make_credentials_json(
        self,
        clusters: dict[str, dict[str, object]] | None = None,
    ) -> str:
        """Create credentials JSON for tests."""
        if clusters is None:
            clusters = {
                "prod": {"type": "token", "token": "test-token"},
            }
        return json.dumps({"clusters": clusters})

    @pytest.mark.asyncio
    async def test_no_credentials_returns_failure(self) -> None:
        """Return failure when credentials is None."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        result = await provider.test_connection(config, None)
        assert result.success is False
        assert "No credentials" in result.message

    @pytest.mark.asyncio
    async def test_empty_credentials_returns_failure(self) -> None:
        """Return failure when credentials is empty string."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        result = await provider.test_connection(config, "")
        assert result.success is False
        assert "No credentials" in result.message

    @pytest.mark.asyncio
    async def test_invalid_credentials_json_returns_failure(self) -> None:
        """Return failure for invalid JSON credentials."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        result = await provider.test_connection(config, "not-json")
        assert result.success is False
        assert "Invalid credentials" in result.message

    @pytest.mark.asyncio
    async def test_missing_cluster_credential_returns_failure(self) -> None:
        """Return failure when credential for configured cluster is absent."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        # credential for prod cluster is absent
        credentials_json = json.dumps({"clusters": {}})
        result = await provider.test_connection(config, credentials_json)
        assert result.success is False
        assert "no credential" in result.message

    @pytest.mark.asyncio
    async def test_successful_connection(self) -> None:
        """Return success=True when all clusters connect successfully."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        credentials_json = self._make_credentials_json()

        mock_version = MagicMock()
        mock_version.git_version = "1.28.3"

        with (
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "azents.engine.tools.kubernetes.VersionApi",
            ) as mock_version_cls,
        ):
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_create.return_value = mock_client
            mock_version_cls.return_value.get_code = AsyncMock(
                return_value=mock_version,
            )

            result = await provider.test_connection(config, credentials_json)

        assert result.success is True
        assert "v1.28.3" in result.message
        assert "prod" in result.message
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_api_client_creation_failure(self) -> None:
        """Report cluster as FAILED when API client creation fails."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        credentials_json = self._make_credentials_json()

        with patch(
            "azents.engine.tools.kubernetes.create_exec_api_client",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Connection refused"),
        ):
            result = await provider.test_connection(config, credentials_json)

        assert result.success is False
        assert "FAILED" in result.message
        assert "Connection refused" in result.message

    @pytest.mark.asyncio
    async def test_version_api_failure(self) -> None:
        """Report cluster as FAILED when VersionApi call fails."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        credentials_json = self._make_credentials_json()

        with (
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "azents.engine.tools.kubernetes.VersionApi",
            ) as mock_version_cls,
        ):
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_create.return_value = mock_client
            mock_version_cls.return_value.get_code = AsyncMock(
                side_effect=ApiException(status=401, reason="Unauthorized"),
            )

            result = await provider.test_connection(config, credentials_json)

        assert result.success is False
        assert "401" in result.message
        assert "Unauthorized" in result.message
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multi_cluster_partial_failure(self) -> None:
        """Report partial failure even when only some of multiple clusters fail."""
        provider = KubernetesToolkitProvider()
        config = self._make_config(
            clusters=[
                ClusterConfig(
                    name="prod",
                    auth_type="token",
                    api_server="https://prod.example.com",
                ),
                ClusterConfig(
                    name="staging",
                    auth_type="token",
                    api_server="https://staging.example.com",
                ),
            ],
        )
        credentials_json = json.dumps(
            {
                "clusters": {
                    "prod": {"type": "token", "token": "prod-token"},
                    "staging": {"type": "token", "token": "staging-token"},
                },
            }
        )

        mock_version_ok = MagicMock()
        mock_version_ok.git_version = "1.28.3"

        call_count = 0

        async def _get_code_side_effect() -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_version_ok
            raise ApiException(status=403, reason="Forbidden")

        with (
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "azents.engine.tools.kubernetes.VersionApi",
            ) as mock_version_cls,
        ):
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_create.return_value = mock_client
            mock_version_cls.return_value.get_code = _get_code_side_effect

            result = await provider.test_connection(config, credentials_json)

        assert result.success is False
        assert "Partial failure" in result.message
        assert "v1.28.3" in result.message
        assert "FAILED" in result.message

    @pytest.mark.asyncio
    async def test_multi_cluster_all_success(self) -> None:
        """Return success=True when all multiple clusters succeed."""
        provider = KubernetesToolkitProvider()
        config = self._make_config(
            clusters=[
                ClusterConfig(
                    name="prod",
                    auth_type="token",
                    api_server="https://prod.example.com",
                ),
                ClusterConfig(
                    name="staging",
                    auth_type="token",
                    api_server="https://staging.example.com",
                ),
            ],
        )
        credentials_json = json.dumps(
            {
                "clusters": {
                    "prod": {"type": "token", "token": "prod-token"},
                    "staging": {"type": "token", "token": "staging-token"},
                },
            }
        )

        mock_version = MagicMock()
        mock_version.git_version = "1.28.3"

        with (
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "azents.engine.tools.kubernetes.VersionApi",
            ) as mock_version_cls,
        ):
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_create.return_value = mock_client
            mock_version_cls.return_value.get_code = AsyncMock(
                return_value=mock_version,
            )

            result = await provider.test_connection(config, credentials_json)

        assert result.success is True
        assert "Connected" in result.message
        assert "prod" in result.message
        assert "staging" in result.message

    @pytest.mark.asyncio
    async def test_config_error_returns_failure(self) -> None:
        """Report config error when create_exec_api_client raises ValueError."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        credentials_json = self._make_credentials_json()

        with patch(
            "azents.engine.tools.kubernetes.create_exec_api_client",
            new_callable=AsyncMock,
            side_effect=ValueError("api_server is required"),
        ):
            result = await provider.test_connection(config, credentials_json)

        assert result.success is False
        assert "config" in result.message
        assert "api_server" in result.message

    @pytest.mark.asyncio
    async def test_network_error_on_version_check(self) -> None:
        """Report FAILED when network error occurs during VersionApi call."""
        provider = KubernetesToolkitProvider()
        config = self._make_config()
        credentials_json = self._make_credentials_json()

        with (
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                new_callable=AsyncMock,
            ) as mock_create,
            patch(
                "azents.engine.tools.kubernetes.VersionApi",
            ) as mock_version_cls,
        ):
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_create.return_value = mock_client
            mock_version_cls.return_value.get_code = AsyncMock(
                side_effect=ConnectionError("Connection timed out"),
            )

            result = await provider.test_connection(config, credentials_json)

        assert result.success is False
        assert "network" in result.message
        assert "Connection timed out" in result.message
        mock_client.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# KubernetesToolkit create_tools tests
# ---------------------------------------------------------------------------


def _make_toolkit(
    *,
    read_only: bool = True,
    has_clients: bool = True,
) -> KubernetesToolkit:
    """Create KubernetesToolkit for tests."""
    config = KubernetesToolkitConfig(
        clusters=[ClusterConfig(name="prod", auth_type="token")],
        read_only=read_only,
    )
    if has_clients:
        mock_client = MagicMock()
        mock_exec_client = MagicMock()
        mock_cache = MagicMock(spec=ResourceDiscoveryCache)
        return KubernetesToolkit(
            config=config,
            clients={"prod": mock_client},
            exec_clients={"prod": mock_exec_client},
            discovery_caches={"prod": mock_cache},
        )
    return KubernetesToolkit(
        config=config,
        clients={},
        exec_clients={},
        discovery_caches={},
    )


class TestKubernetesToolkitCreateTools:
    """KubernetesToolkit.create_tools() tests."""

    @pytest.mark.asyncio
    async def test_no_clients_still_returns_tools_for_lazy_load(self) -> None:
        """Expose tools for lazy load even without clients."""
        toolkit = _make_toolkit(has_clients=False)
        context = _make_context()
        state = await toolkit.update_context(context)
        tools = state.tools
        assert {tool.spec.name for tool in tools} == {
            "k8s_list",
            "k8s_get",
            "k8s_logs",
            "k8s_events",
            "k8s_api_resources",
        }

    @pytest.mark.asyncio
    async def test_read_only_returns_five_tools(self) -> None:
        """Return five read tools when read_only=True."""
        toolkit = _make_toolkit(read_only=True)
        context = _make_context()
        state = await toolkit.update_context(context)
        tools = state.tools
        assert len(tools) == 5
        tool_names = {t.spec.name for t in tools}
        assert tool_names == {
            "k8s_list",
            "k8s_get",
            "k8s_logs",
            "k8s_events",
            "k8s_api_resources",
        }

    @pytest.mark.asyncio
    async def test_read_write_returns_eight_tools(self) -> None:
        """Return eight tools (read 5 + write 3) when read_only=False."""
        toolkit = _make_toolkit(read_only=False)
        context = _make_context()
        state = await toolkit.update_context(context)
        tools = state.tools
        assert len(tools) == 8
        tool_names = {t.spec.name for t in tools}
        assert tool_names == {
            "k8s_list",
            "k8s_get",
            "k8s_logs",
            "k8s_events",
            "k8s_api_resources",
            "k8s_apply",
            "k8s_delete",
            "k8s_exec",
        }

    @pytest.mark.asyncio
    async def test_read_only_excludes_write_tools(self) -> None:
        """Check that write tools are not included when read_only=True."""
        toolkit = _make_toolkit(read_only=True)
        context = _make_context()
        state = await toolkit.update_context(context)
        tools = state.tools
        tool_names = {t.spec.name for t in tools}
        assert "k8s_apply" not in tool_names
        assert "k8s_delete" not in tool_names
        assert "k8s_exec" not in tool_names


class TestKubernetesToolkitLifecycle:
    """KubernetesToolkit session lifecycle tests."""

    @pytest.mark.asyncio
    async def test_aexit_closes_lightkube_and_exec_clients(self) -> None:
        """Close all lightkube/exec clients on session exit."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
        )
        lightkube_client = MagicMock()
        lightkube_client.close = AsyncMock()
        exec_client = MagicMock()
        exec_client.close = AsyncMock()
        cache = MagicMock(spec=ResourceDiscoveryCache)
        toolkit = KubernetesToolkit(
            config=config,
            clients={"prod": lightkube_client},
            exec_clients={"prod": exec_client},
            discovery_caches={"prod": cache},
        )

        await toolkit.__aexit__(None, None, None)

        lightkube_client.close.assert_awaited_once()
        exec_client.close.assert_awaited_once()
        assert toolkit._clients == {}  # pyright: ignore[reportPrivateUsage] — validate internal state after close in tests
        assert toolkit._exec_clients == {}  # pyright: ignore[reportPrivateUsage] — validate internal state after close in tests
        assert toolkit._discovery_caches == {}  # pyright: ignore[reportPrivateUsage] — validate internal state after close in tests

    @pytest.mark.asyncio
    async def test_aexit_closes_remaining_clients_when_one_close_fails(self) -> None:
        """Some close failures do not block cleanup of other clients."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
        )
        lightkube_client = MagicMock()
        lightkube_client.close = AsyncMock(side_effect=RuntimeError("close failed"))
        exec_client = MagicMock()
        exec_client.close = AsyncMock()
        toolkit = KubernetesToolkit(
            config=config,
            clients={"prod": lightkube_client},
            exec_clients={"prod": exec_client},
            discovery_caches={"prod": MagicMock(spec=ResourceDiscoveryCache)},
        )

        await toolkit.__aexit__(None, None, None)

        lightkube_client.close.assert_awaited_once()
        exec_client.close.assert_awaited_once()
        assert toolkit._clients == {}  # pyright: ignore[reportPrivateUsage] — validate internal state after close in tests
        assert toolkit._exec_clients == {}  # pyright: ignore[reportPrivateUsage] — validate internal state after close in tests

    @pytest.mark.asyncio
    async def test_lazy_load_closes_clients_when_cancelled_mid_discovery(
        self,
    ) -> None:
        """Close clients when lazy load is cancelled."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="staging", auth_type="token")],
        )
        credentials = KubernetesCredentials(
            clusters={"staging": TokenCredential(token="staging-token")},
        ).model_dump_json()
        context = _make_resolve_context(credentials)
        provider = KubernetesToolkitProvider()

        staging_lightkube = MagicMock()
        staging_lightkube.close = AsyncMock()
        staging_lightkube._client._client = MagicMock()
        staging_exec = MagicMock()
        staging_exec.close = AsyncMock()

        staging_cache = MagicMock(spec=ResourceDiscoveryCache)
        staging_cache.discover = AsyncMock(side_effect=asyncio.CancelledError)

        with (
            patch(
                "azents.engine.tools.kubernetes.create_lightkube_client",
                AsyncMock(return_value=staging_lightkube),
            ),
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                AsyncMock(return_value=staging_exec),
            ),
            patch(
                "azents.engine.tools.kubernetes.ResourceDiscoveryCache",
                MagicMock(return_value=staging_cache),
            ),
        ):
            toolkit = await provider.resolve(config, context)
            assert isinstance(toolkit, KubernetesToolkit)
            with pytest.raises(asyncio.CancelledError):
                await toolkit._ensure_cluster_clients("staging")  # pyright: ignore[reportPrivateUsage] — directly validate lazy load cancellation path

        staging_lightkube.close.assert_awaited_once()
        staging_exec.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lazy_load_uses_one_cluster_lock_for_concurrent_calls(self) -> None:
        """Concurrent tool calls perform client load only once with per-cluster lock."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
        )
        credentials = KubernetesCredentials(
            clusters={"prod": TokenCredential(token="prod-token")},
        )
        toolkit = KubernetesToolkit(config=config, credentials=credentials)
        lightkube_client = MagicMock()
        lightkube_client._client._client = MagicMock()
        exec_client = MagicMock()
        cache = MagicMock(spec=ResourceDiscoveryCache)
        cache.discover = AsyncMock()

        with (
            patch(
                "azents.engine.tools.kubernetes.create_lightkube_client",
                AsyncMock(return_value=lightkube_client),
            ) as mock_lightkube,
            patch(
                "azents.engine.tools.kubernetes.create_exec_api_client",
                AsyncMock(return_value=exec_client),
            ) as mock_exec,
            patch(
                "azents.engine.tools.kubernetes.ResourceDiscoveryCache",
                MagicMock(return_value=cache),
            ),
        ):
            first, second = await asyncio.gather(
                toolkit._ensure_cluster_clients("prod"),  # pyright: ignore[reportPrivateUsage] — directly validate lock concurrency path
                toolkit._ensure_cluster_clients("prod"),  # pyright: ignore[reportPrivateUsage] — directly validate lock concurrency path
            )

        assert first == second
        mock_lightkube.assert_awaited_once()
        mock_exec.assert_awaited_once()
        cache.discover.assert_awaited_once()


# ---------------------------------------------------------------------------
# Write tool input model tests
# ---------------------------------------------------------------------------


class TestWriteToolInputModels:
    """Write tool input model validation tests."""

    def test_apply_input_basic(self) -> None:
        """Check K8sApplyInput default fields."""
        inp = K8sApplyInput(
            cluster="prod",
            manifest="apiVersion: v1\nkind: Pod\nmetadata:\n  name: test",
        )
        assert inp.cluster == "prod"
        assert "apiVersion" in inp.manifest

    def test_delete_input_defaults(self) -> None:
        """Check K8sDeleteInput defaults."""
        inp = K8sDeleteInput(
            cluster="prod",
            kind="Deployment",
            name="my-app",
        )
        assert inp.api_version == "v1"
        assert inp.namespace is None

    def test_delete_input_custom(self) -> None:
        """Check K8sDeleteInput custom values."""
        inp = K8sDeleteInput(
            cluster="prod",
            api_version="apps/v1",
            kind="Deployment",
            name="my-app",
            namespace="staging",
        )
        assert inp.api_version == "apps/v1"
        assert inp.namespace == "staging"

    def test_exec_input_basic(self) -> None:
        """Check K8sExecInput default fields."""
        inp = K8sExecInput(
            cluster="prod",
            pod="my-pod",
            command=["ls", "-la"],
        )
        assert inp.pod == "my-pod"
        assert inp.command == ["ls", "-la"]
        assert inp.container is None
        assert inp.namespace is None

    def test_exec_input_with_container(self) -> None:
        """Check that container can be specified in K8sExecInput."""
        inp = K8sExecInput(
            cluster="prod",
            namespace="app",
            pod="my-pod",
            container="sidecar",
            command=["cat", "/etc/config"],
        )
        assert inp.container == "sidecar"
        assert inp.namespace == "app"


# ---------------------------------------------------------------------------
# render_config_prompt tests
# ---------------------------------------------------------------------------


class TestRenderConfigPrompt:
    """render_config_prompt() tests."""

    def test_read_only_prompt(self) -> None:
        """Check prompt in read_only mode."""
        config = KubernetesToolkitConfig(
            clusters=[
                ClusterConfig(name="prod", auth_type="token"),
                ClusterConfig(name="staging", auth_type="kubeconfig"),
            ],
            read_only=True,
            denied_kinds=["Secret"],
        )
        toolkit = KubernetesToolkit(
            config=config,
            clients={"prod": MagicMock()},
            exec_clients={"prod": MagicMock()},
            discovery_caches={"prod": MagicMock()},
        )
        prompt = toolkit._render_config_prompt()  # pyright: ignore[reportPrivateUsage] — directly validate internal method in tests
        assert "prod" in prompt
        assert "staging" in prompt
        assert "read-only" in prompt
        assert "Secret" in prompt

    def test_read_write_prompt(self) -> None:
        """Check prompt in read-write mode."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
            read_only=False,
        )
        toolkit = KubernetesToolkit(
            config=config,
            clients={"prod": MagicMock()},
            exec_clients={"prod": MagicMock()},
            discovery_caches={"prod": MagicMock()},
        )
        prompt = toolkit._render_config_prompt()  # pyright: ignore[reportPrivateUsage] — directly validate internal method in tests
        assert "read-write" in prompt

    def test_allowed_namespaces_in_prompt(self) -> None:
        """Check that allowed_namespaces is included in prompt."""
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
            allowed_namespaces=["app", "monitoring"],
        )
        toolkit = KubernetesToolkit(
            config=config,
            clients={"prod": MagicMock()},
            exec_clients={"prod": MagicMock()},
            discovery_caches={"prod": MagicMock()},
        )
        prompt = toolkit._render_config_prompt()  # pyright: ignore[reportPrivateUsage] — directly validate internal method in tests
        assert "app" in prompt
        assert "monitoring" in prompt
        assert "Allowed namespaces" in prompt


# ---------------------------------------------------------------------------
# Helper: utility to find tool by name
# ---------------------------------------------------------------------------


def _find_tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    """Find tool by name. AssertionError when absent."""
    for t in tools:
        if t.spec.name == name:
            return t
    available = [t.spec.name for t in tools]
    msg = f"Tool '{name}' not found. Available: {available}"
    raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Tool handler feature tests
# ---------------------------------------------------------------------------


class TestKubernetesToolHandlers:
    """Test that Kubernetes tool handler calls k8s API correctly."""

    @pytest.fixture
    def k8s_toolkit(self) -> KubernetesToolkit:
        """KubernetesToolkit in read-write mode."""
        mock_client = MagicMock()
        mock_exec_client = MagicMock()
        mock_cache = MagicMock(spec=ResourceDiscoveryCache)
        config = KubernetesToolkitConfig(
            clusters=[ClusterConfig(name="prod", auth_type="token")],
            read_only=False,
        )
        return KubernetesToolkit(
            config=config,
            clients={"prod": mock_client},
            exec_clients={"prod": mock_exec_client},
            discovery_caches={"prod": mock_cache},
        )

    @pytest.mark.asyncio
    async def test_k8s_list_handler_calls_lightkube(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_list handler calls lightkube client.list()."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        # lightkube list() returns async iterator
        mock_item = {"metadata": {"name": "test-pod"}}

        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            """lightkube list() mock — async generator."""
            yield mock_item

        # Mock get_resource_class of discovery cache
        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "api_version": "v1",
                    "kind": "Pod",
                    "namespace": "default",
                }
            )
        )

        assert isinstance(result, str)
        assert "test-pod" in result
        assert "Pagination" not in result

    @pytest.mark.asyncio
    async def test_k8s_list_pagination_with_offset(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_list skips by offset and returns by limit."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        # Mock returning five items: offset=2, limit=2 returns only 3rd-4th
        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            for i in range(5):
                yield {"metadata": {"name": f"pod-{i}"}}

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Pod",
                    "namespace": "default",
                    "offset": 2,
                    "limit": 2,
                }
            )
        )

        assert isinstance(result, str)
        assert "pod-2" in result
        assert "pod-3" in result
        assert "pod-0" not in result
        assert "pod-1" not in result
        assert "offset: 2" in result
        assert "next_offset: 4" in result

    @pytest.mark.asyncio
    async def test_k8s_list_pagination_no_more_items(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_list does not include next_offset when no remaining item exists."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        # Return three items: offset=1, limit=50 returns only two, has_more=False
        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            for i in range(3):
                yield {"metadata": {"name": f"pod-{i}"}}

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Pod",
                    "namespace": "default",
                    "offset": 1,
                    "limit": 50,
                }
            )
        )

        assert isinstance(result, str)
        assert "pod-1" in result
        assert "pod-2" in result
        assert "pod-0" not in result
        assert "offset: 1" in result
        assert "count: 2" in result
        assert "next_offset" not in result

    @pytest.mark.asyncio
    async def test_k8s_get_handler_calls_lightkube(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_get handler calls lightkube client.get()."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_get")

        mock_result = {"metadata": {"name": "my-deploy"}, "spec": {}}
        mock_res_class = MagicMock()

        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].get = AsyncMock(return_value=mock_result)  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "api_version": "apps/v1",
                    "kind": "Deployment",
                    "name": "my-deploy",
                    "namespace": "default",
                }
            )
        )

        assert isinstance(result, str)
        assert "my-deploy" in result

    @pytest.mark.asyncio
    async def test_k8s_logs_handler_calls_lightkube(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_logs handler calls lightkube client.log()."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_logs")

        async def _mock_log(*_args: object, **_kwargs: object) -> object:
            """lightkube log() mock — async generator."""
            yield "log line 1\n"
            yield "log line 2\n"

        k8s_toolkit._clients["prod"].log = _mock_log  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "pod": "my-pod",
                    "namespace": "default",
                    "tail_lines": 50,
                }
            )
        )

        assert isinstance(result, str)
        assert "log line 1" in result

    @pytest.mark.asyncio
    async def test_k8s_exec_handler_uses_post_exec_subresource(
        self,
        k8s_toolkit: KubernetesToolkit,
    ) -> None:
        """k8s_exec uses POST because pods/exec RBAC grants create, not get."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_exec")
        ws_client = MagicMock()
        ws_client.close = AsyncMock()
        core_v1 = MagicMock()
        core_v1.connect_post_namespaced_pod_exec = AsyncMock(return_value="exec output")
        core_v1.connect_get_namespaced_pod_exec = AsyncMock(
            side_effect=AssertionError("GET exec must not be used"),
        )

        with (
            patch(
                "azents.engine.tools.kubernetes.WsApiClient",
                MagicMock(return_value=ws_client),
            ),
            patch(
                "azents.engine.tools.kubernetes.CoreV1Api",
                MagicMock(return_value=core_v1),
            ),
        ):
            result = await tool.handler(
                json.dumps(
                    {
                        "cluster": "prod",
                        "namespace": "default",
                        "pod": "my-pod",
                        "container": "app",
                        "command": ["id"],
                    }
                )
            )

        assert result == "exec output"
        core_v1.connect_post_namespaced_pod_exec.assert_awaited_once_with(
            name="my-pod",
            namespace="default",
            command=["id"],
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            container="app",
        )
        core_v1.connect_get_namespaced_pod_exec.assert_not_called()
        ws_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_k8s_list_output_filter_projects_fields(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """Project fields with JMESPath when output_filter is specified."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            yield {
                "metadata": {"name": "pod-a", "namespace": "default"},
                "status": {"phase": "Running"},
                "spec": {"nodeName": "node-1"},
            }
            yield {
                "metadata": {"name": "pod-b", "namespace": "default"},
                "status": {"phase": "Pending"},
                "spec": {"nodeName": "node-2"},
            }

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Pod",
                    "namespace": "default",
                    "output_filter": "[*].{name: metadata.name, phase: status.phase}",
                }
            )
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == [
            {"name": "pod-a", "phase": "Running"},
            {"name": "pod-b", "phase": "Pending"},
        ]

    @pytest.mark.asyncio
    async def test_k8s_list_output_filter_with_condition(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """k8s_list filters + projects with output_filter condition."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            yield {
                "metadata": {"name": "pod-a"},
                "status": {"phase": "Running"},
            }
            yield {
                "metadata": {"name": "pod-b"},
                "status": {"phase": "Pending"},
            }
            yield {
                "metadata": {"name": "pod-c"},
                "status": {"phase": "Running"},
            }

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Pod",
                    "namespace": "default",
                    "output_filter": "[?status.phase == `Running`].metadata.name",
                }
            )
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == ["pod-a", "pod-c"]

    @pytest.mark.asyncio
    async def test_k8s_list_invalid_output_filter_raises_error(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """Invalid output_filter raises FunctionToolError."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        async def _mock_list(*_args: object, **_kwargs: object) -> object:
            yield {"metadata": {"name": "pod-a"}}

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].list = _mock_list  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        with pytest.raises(FunctionToolError, match="Invalid output_filter"):
            await tool.handler(
                json.dumps(
                    {
                        "cluster": "prod",
                        "kind": "Pod",
                        "namespace": "default",
                        "output_filter": "[*].{invalid",
                    }
                )
            )

    @pytest.mark.asyncio
    async def test_k8s_get_output_filter_projects_fields(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """When output_filter is specified for k8s_get, project fields with JMESPath."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_get")

        mock_result = {
            "metadata": {"name": "my-deploy", "namespace": "default"},
            "spec": {"replicas": 3},
            "status": {"readyReplicas": 2},
        }
        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].get = AsyncMock(return_value=mock_result)  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Deployment",
                    "name": "my-deploy",
                    "namespace": "default",
                    "output_filter": (
                        "{name: metadata.name,"
                        " replicas: spec.replicas,"
                        " ready: status.readyReplicas}"
                    ),
                }
            )
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == {"name": "my-deploy", "replicas": 3, "ready": 2}

    @pytest.mark.asyncio
    async def test_k8s_get_output_filter_extracts_single_field(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """Extract single field from k8s_get with output_filter."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_get")

        mock_result = {
            "metadata": {
                "name": "my-deploy",
                "labels": {"app": "web", "env": "prod"},
            },
            "spec": {},
        }
        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )
        k8s_toolkit._clients["prod"].get = AsyncMock(return_value=mock_result)  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests

        result = await tool.handler(
            json.dumps(
                {
                    "cluster": "prod",
                    "kind": "Deployment",
                    "name": "my-deploy",
                    "namespace": "default",
                    "output_filter": "metadata.labels",
                }
            )
        )

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed == {"app": "web", "env": "prod"}

    @pytest.mark.asyncio
    async def test_k8s_list_denied_kind_raises_error(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """Fetching kind included in denied_kinds raises FunctionToolError."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        with pytest.raises(FunctionToolError, match="Access denied"):
            await tool.handler(
                json.dumps(
                    {
                        "cluster": "prod",
                        "api_version": "v1",
                        "kind": "Secret",
                        "namespace": "default",
                    }
                )
            )

    @pytest.mark.asyncio
    async def test_k8s_list_invalid_cluster_raises_error(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """Specifying nonexistent cluster raises FunctionToolError."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        with pytest.raises(FunctionToolError, match="not found"):
            await tool.handler(
                json.dumps(
                    {
                        "cluster": "nonexistent",
                        "api_version": "v1",
                        "kind": "Pod",
                    }
                )
            )

    @pytest.mark.asyncio
    async def test_k8s_list_api_error_raises_function_tool_error(
        self, k8s_toolkit: KubernetesToolkit
    ) -> None:
        """lightkube ApiError is converted to FunctionToolError."""
        context = _make_context()
        state = await k8s_toolkit.update_context(context)
        tool = _find_tool(state.tools, "k8s_list")

        mock_res_class = MagicMock()
        k8s_toolkit._discovery_caches["prod"].get_resource_class = MagicMock(  # pyright: ignore[reportPrivateUsage] — directly set internal attribute in tests
            return_value=mock_res_class
        )

        # Mock async iterator that raises ApiError
        status_dict = {"code": 403, "reason": "Forbidden", "message": "Forbidden"}

        async def _mock_list_error(*_args: object, **_kwargs: object) -> object:
            """Mock list that raises ApiError."""
            raise ApiError(status=status_dict)
            yield  # unreachable yield to make async generator

        k8s_toolkit._clients["prod"].list = _mock_list_error  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue] — directly set internal attribute in tests

        with pytest.raises(FunctionToolError, match="403.*Forbidden"):
            await tool.handler(
                json.dumps(
                    {
                        "cluster": "prod",
                        "api_version": "v1",
                        "kind": "Pod",
                        "namespace": "default",
                    }
                )
            )
