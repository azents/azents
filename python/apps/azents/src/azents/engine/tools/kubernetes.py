"""Kubernetes Toolkit.

lightkube-based native Toolkit.
Provides Generic tools for all resource types, including CRDs.
Supports kubeconfig/token/EKS/GKE authentication.
Only exec uses kubernetes_asyncio WsApiClient; lightkube lacks WebSocket.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from textwrap import dedent
from typing import Any, ClassVar

import httpx
import jmespath
import yaml
from botocore.exceptions import ClientError as BotoClientError
from jmespath.exceptions import JMESPathError
from kubernetes_asyncio.client import ApiClient, CoreV1Api, VersionApi
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.stream import WsApiClient
from lightkube import ApiError, AsyncClient
from lightkube.resources.core_v1 import Event
from pydantic import BaseModel, Field, ValidationError

from azents.core.tools import (
    ClusterConfig,
    KubernetesToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.kubernetes_auth import (
    KubernetesCredentials,
    create_exec_api_client,
    create_lightkube_client,
    parse_credentials,
)
from azents.engine.tools.kubernetes_discovery import ResourceDiscoveryCache

logger = logging.getLogger(__name__)

# Error types caused by user settings/infra issues (warning level)
_CLIENT_ERRORS = (ConnectionError, TimeoutError, OSError, ApiException, BotoClientError)
KubernetesClusterClients = tuple[AsyncClient, ApiClient, ResourceDiscoveryCache]
KubernetesClientResolver = Callable[[str], Awaitable[KubernetesClusterClients]]


async def _close_kubernetes_clients(
    *clients: AsyncClient | ApiClient | None,
) -> None:
    """Close created Kubernetes clients as much as possible.

    :param clients: lightkube/kubernetes_asyncio client list to clean up
    """
    close_tasks = [client.close() for client in clients if client is not None]
    if not close_tasks:
        return

    results = await asyncio.gather(*close_tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.warning(
                "Failed to close Kubernetes client",
                exc_info=(type(result), result, result.__traceback__),
            )


# ---------------------------------------------------------------------------
# Security utilities
# ---------------------------------------------------------------------------


def check_access(
    config: KubernetesToolkitConfig,
    kind: str,
    namespace: str | None,
) -> None:
    """Check access permission. Raise FunctionToolError on violation.

    :param config: Kubernetes Toolkit settings
    :param kind: Resource kind
    :param namespace: Target namespace
    :raises FunctionToolError: When access is denied
    """
    if kind in config.denied_kinds:
        raise FunctionToolError(f"Access denied: {kind} is in denied_kinds.")
    if config.allowed_namespaces is not None and namespace is not None:
        if namespace not in config.allowed_namespaces:
            raise FunctionToolError(
                f"Access denied: namespace '{namespace}' is not in allowed_namespaces."
            )


def resolve_namespace(
    cluster_config: ClusterConfig,
    namespace: str | None,
) -> str:
    """Return cluster default_namespace when namespace is None.

    :param cluster_config: Cluster settings
    :param namespace: User-specified namespace; use default when None
    :return: Namespace to use
    """
    return namespace if namespace is not None else cluster_config.default_namespace


def _get_cluster_config(
    config: KubernetesToolkitConfig,
    cluster_name: str,
) -> ClusterConfig:
    """Fetch ClusterConfig by cluster name.

    :param config: Kubernetes Toolkit settings
    :param cluster_name: Cluster name
    :return: ClusterConfig
    :raises FunctionToolError: When cluster is not found
    """
    for cluster_config in config.clusters:
        if cluster_config.name == cluster_name:
            return cluster_config
    raise FunctionToolError(f"Cluster config for '{cluster_name}' not found.")


def _parse_selector(selector: str) -> dict[str, Any]:
    """Parse comma-separated key=value string into dict.

    :param selector: String in "app=nginx,env=prod" format
    :return: dict in {"app": "nginx", "env": "prod"} form
    """
    result: dict[str, Any] = {}
    for raw_part in selector.split(","):
        part = raw_part.strip()
        if "=" in part:
            key, value = part.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _format_resource_list(items: list[dict[str, Any]]) -> str:
    """Format resource list into readable text.

    :param items: Resource dict list
    :return: Formatted text
    """
    if not items:
        return "No resources found."
    result = json.dumps(items, indent=2, default=str)
    return result


def _apply_output_filter(data: object, expression: str) -> str:
    """Apply JMESPath expression to JSON data and return result.

    :param data: Python object to apply JMESPath to, such as dict or list
    :param expression: JMESPath expression string
    :return: JSON string of filtered result
    :raises FunctionToolError: When expression is invalid
    """
    try:
        result = jmespath.search(expression, data)
    except JMESPathError as exc:
        raise FunctionToolError(f"Invalid output_filter expression: {exc}") from None
    return json.dumps(result, indent=2, default=str)


# ---------------------------------------------------------------------------
# Tool input models
# ---------------------------------------------------------------------------


class K8sListInput(BaseModel):
    """k8s_list tool input."""

    cluster: str = Field(description="Cluster name")
    api_version: str = Field(default="v1", description="API version (e.g. v1, apps/v1)")
    kind: str = Field(description="Resource kind (e.g. Pod, Deployment, Service)")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )
    label_selector: str | None = Field(
        default=None, description="Label selector (e.g. app=nginx)"
    )
    field_selector: str | None = Field(
        default=None, description="Field selector (e.g. status.phase=Running)"
    )
    limit: int = Field(default=50, ge=1, le=200, description="Max number of results")
    offset: int = Field(
        default=0, ge=0, description="Number of items to skip for pagination"
    )
    output_filter: str | None = Field(
        default=None,
        description=(
            "JMESPath expression to filter/project the result. "
            "Applied to the list of items. "
            "Examples: "
            "'[*].{name: metadata.name, phase: status.phase}' "
            "- project specific fields; "
            "'[?status.phase == `Running`].metadata.name' "
            "- filter and project"
        ),
    )


class K8sGetInput(BaseModel):
    """k8s_get tool input."""

    cluster: str = Field(description="Cluster name")
    api_version: str = Field(default="v1", description="API version")
    kind: str = Field(description="Resource kind")
    name: str = Field(description="Resource name")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )
    output_filter: str | None = Field(
        default=None,
        description=(
            "JMESPath expression to filter/project the result. "
            "Applied to the resource object. "
            "Examples: "
            "'{name: metadata.name, replicas: spec.replicas}' "
            "- project specific fields; "
            "'metadata.labels' - extract a single field"
        ),
    )


class K8sLogsInput(BaseModel):
    """k8s_logs tool input."""

    cluster: str = Field(description="Cluster name")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )
    pod: str = Field(description="Pod name")
    container: str | None = Field(
        default=None, description="Container name (for multi-container pods)"
    )
    tail_lines: int = Field(default=100, ge=1, le=1000, description="Last N lines")
    since_seconds: int | None = Field(
        default=None, description="Only return logs newer than N seconds"
    )


class K8sEventsInput(BaseModel):
    """k8s_events tool input."""

    cluster: str = Field(description="Cluster name")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )
    kind: str | None = Field(
        default=None,
        description="Filter events by involved object kind (e.g. Pod, Deployment)",
    )
    name: str | None = Field(
        default=None, description="Filter events by involved object name"
    )
    output_filter: str | None = Field(
        default=None,
        description=(
            "JMESPath expression to filter/project the result. "
            "Applied to the list of events. "
            "Examples: "
            "'[*].{reason: reason, message: message, object: involvedObject.name}' "
            "- project specific fields"
        ),
    )


class K8sApiResourcesInput(BaseModel):
    """k8s_api_resources tool input."""

    cluster: str = Field(description="Cluster name")


class K8sApplyInput(BaseModel):
    """k8s_apply tool input."""

    cluster: str = Field(description="Cluster name")
    manifest: str = Field(description="YAML manifest string")


class K8sDeleteInput(BaseModel):
    """k8s_delete tool input."""

    cluster: str = Field(description="Cluster name")
    api_version: str = Field(default="v1", description="API version")
    kind: str = Field(description="Resource kind (e.g. Pod, Deployment)")
    name: str = Field(description="Resource name")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )


class K8sExecInput(BaseModel):
    """k8s_exec tool input."""

    cluster: str = Field(description="Cluster name")
    namespace: str | None = Field(
        default=None, description="Namespace (uses cluster default if omitted)"
    )
    pod: str = Field(description="Pod name")
    container: str | None = Field(
        default=None, description="Container name (for multi-container pods)"
    )
    command: list[str] = Field(description="Command to execute")


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def _make_list_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_list Create tool."""

    async def k8s_list(args: K8sListInput) -> str:
        """List Kubernetes resources by kind. Supports label and field selectors."""
        client, _, cache = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        check_access(config, args.kind, ns)

        try:
            res_class = cache.get_resource_class(args.api_version, args.kind)
            labels = (
                _parse_selector(args.label_selector) if args.label_selector else None
            )
            fields = (
                _parse_selector(args.field_selector) if args.field_selector else None
            )
            items: list[dict[str, Any]] = []
            skipped = 0
            end = args.offset + args.limit
            has_more = False
            async for item in client.list(
                res_class,  # pyright: ignore[reportArgumentType]  # lightkube overload does not accept union return type of get_resource_class()
                namespace=ns,
                labels=labels,
                fields=fields,
            ):
                if skipped < args.offset:
                    skipped += 1
                    continue
                items.append(dict(item))
                if len(items) >= args.limit:
                    # Set has_more=True without iterating once more to check next item
                    # because exact total is unknown
                    has_more = True
                    break

            if args.output_filter:
                output = _apply_output_filter(items, args.output_filter)
            else:
                output = _format_resource_list(items)
            if args.offset > 0 or has_more:
                parts = [
                    "\n\n--- Pagination ---",
                    f"offset: {args.offset}",
                    f"limit: {args.limit}",
                    f"count: {len(items)}",
                ]
                if has_more:
                    parts.append(f"next_offset: {end}")
                output += "\n".join(parts)
            return output
        except KeyError as exc:
            raise FunctionToolError(str(exc)) from None
        except ApiError as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None
        except httpx.TimeoutException:
            raise FunctionToolError(
                "Kubernetes API request timed out. Check cluster connectivity."
            ) from None

    return make_tool(k8s_list, input_model=K8sListInput)


def _make_get_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_get Create tool."""

    async def k8s_get(args: K8sGetInput) -> str:
        """Get a specific Kubernetes resource by name."""
        client, _, cache = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        check_access(config, args.kind, ns)

        try:
            res_class = cache.get_resource_class(args.api_version, args.kind)
            result = await client.get(
                res_class,  # pyright: ignore[reportArgumentType]  # lightkube overload does not accept union return type of get_resource_class()
                name=args.name,
                namespace=ns,
            )
            resource = dict(result)
            if args.output_filter:
                return _apply_output_filter(resource, args.output_filter)
            return json.dumps(resource, indent=2, default=str)
        except KeyError as exc:
            raise FunctionToolError(str(exc)) from None
        except ApiError as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None
        except httpx.TimeoutException:
            raise FunctionToolError(
                "Kubernetes API request timed out. Check cluster connectivity."
            ) from None

    return make_tool(k8s_get, input_model=K8sGetInput)


def _make_logs_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_logs Create tool."""

    async def k8s_logs(args: K8sLogsInput) -> str:
        """Get logs from a Kubernetes pod."""
        client, _, _ = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        check_access(config, "Pod", ns)

        try:
            kwargs: dict[str, Any] = {}
            if args.container:
                kwargs["container"] = args.container
            if args.since_seconds is not None:
                kwargs["since"] = args.since_seconds

            lines: list[str] = []
            async for line in client.log(
                args.pod,
                namespace=ns,
                tail_lines=args.tail_lines,
                **kwargs,
            ):
                lines.append(line)

            log_text = "".join(lines)
            if not log_text:
                return "No logs found."
            return log_text
        except ApiError as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None
        except httpx.TimeoutException:
            raise FunctionToolError(
                "Kubernetes API request timed out. Check cluster connectivity."
            ) from None

    return make_tool(k8s_logs, input_model=K8sLogsInput)


def _make_events_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_events Create tool."""

    async def k8s_events(args: K8sEventsInput) -> str:
        """Get Kubernetes events, optionally filtered by involved object."""
        client, _, _ = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        if args.kind:
            check_access(config, args.kind, ns)
        check_access(config, "Event", ns)

        try:
            # Filter by involvedObject
            fields: dict[str, Any] = {}
            if args.kind:
                fields["involvedObject.kind"] = args.kind
            if args.name:
                fields["involvedObject.name"] = args.name

            items: list[dict[str, Any]] = []
            async for event in client.list(
                Event,
                namespace=ns,
                fields=fields if fields else None,
            ):
                items.append(event.to_dict())
            if args.output_filter:
                return _apply_output_filter(items, args.output_filter)
            return _format_resource_list(items)
        except ApiError as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None
        except httpx.TimeoutException:
            raise FunctionToolError(
                "Kubernetes API request timed out. Check cluster connectivity."
            ) from None

    return make_tool(k8s_events, input_model=K8sEventsInput)


def _make_api_resources_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_api_resources Create tool."""

    async def k8s_api_resources(args: K8sApiResourcesInput) -> str:
        """List available API resource types in the cluster."""
        _, _, cache = await client_resolver(args.cluster)

        resources = cache.list_all()
        lines: list[str] = []
        for r in resources:
            if r.group:
                lines.append(
                    f"{r.group}/{r.version}/{r.kind} (namespaced={r.namespaced})"
                )
            else:
                lines.append(f"{r.version}/{r.kind} (namespaced={r.namespaced})")

        if not lines:
            return "No API resources found."
        return "\n".join(lines)

    return make_tool(k8s_api_resources, input_model=K8sApiResourcesInput)


# ---------------------------------------------------------------------------
# Write tool factories
# ---------------------------------------------------------------------------


def _make_apply_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_apply Create tool."""

    async def k8s_apply(args: K8sApplyInput) -> str:
        """Apply a YAML manifest to the cluster using server-side apply."""
        client, _, cache = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)

        try:
            docs = list(yaml.safe_load_all(args.manifest))
        except yaml.YAMLError as exc:
            raise FunctionToolError(f"Invalid YAML manifest: {exc}") from None

        if not docs:
            raise FunctionToolError("Empty manifest: no YAML documents found.")

        results: list[str] = []

        for doc in docs:
            if doc is None:
                continue

            api_version = doc.get("apiVersion")
            kind = doc.get("kind")
            metadata = doc.get("metadata", {})
            name = metadata.get("name", "<unknown>")
            namespace = metadata.get(
                "namespace",
                resolve_namespace(cluster_config, None),
            )

            if not api_version or not kind:
                raise FunctionToolError(
                    "Manifest must have apiVersion and kind fields."
                )

            check_access(config, kind, namespace)

            try:
                res_class = cache.get_resource_class(api_version, kind)
                obj = res_class(doc)
                await client.apply(obj, field_manager="azents-toolkit")
                results.append(f"{kind}/{name} applied in namespace {namespace}")
            except KeyError as exc:
                raise FunctionToolError(str(exc)) from None
            except ApiError as exc:
                raise FunctionToolError(
                    f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
                ) from None

        return "\n".join(results)

    return make_tool(k8s_apply, input_model=K8sApplyInput)


def _make_delete_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_delete Create tool."""

    async def k8s_delete(args: K8sDeleteInput) -> str:
        """Delete a Kubernetes resource by name."""
        client, _, cache = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        check_access(config, args.kind, ns)

        try:
            res_class = cache.get_resource_class(args.api_version, args.kind)
            await client.delete(
                res_class,  # pyright: ignore[reportArgumentType]  # lightkube overload does not accept union return type of get_resource_class()
                name=args.name,
                namespace=ns,
            )
            return f"{args.kind}/{args.name} deleted from namespace {ns}"
        except KeyError as exc:
            raise FunctionToolError(str(exc)) from None
        except ApiError as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status.code}): {exc.status.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None
        except httpx.TimeoutException:
            raise FunctionToolError(
                "Kubernetes API request timed out. Check cluster connectivity."
            ) from None

    return make_tool(k8s_delete, input_model=K8sDeleteInput)


def _make_exec_tool(
    client_resolver: KubernetesClientResolver,
    config: KubernetesToolkitConfig,
) -> FunctionTool:
    """k8s_exec Create tool.

    exec is WebSocket-based, so use kubernetes_asyncio WsApiClient.
    lightkube does not support WebSocket exec.
    """

    async def k8s_exec(args: K8sExecInput) -> str:
        """Execute a command in a Kubernetes pod."""
        _, api_client, _ = await client_resolver(args.cluster)
        cluster_config = _get_cluster_config(config, args.cluster)
        ns = resolve_namespace(cluster_config, args.namespace)
        check_access(config, "Pod", ns)

        try:
            # Run WebSocket-based exec with WsApiClient
            ws_client = WsApiClient(configuration=api_client.configuration)
            try:
                core_v1 = CoreV1Api(ws_client)
                kwargs: dict[str, Any] = {
                    "name": args.pod,
                    "namespace": ns,
                    "command": args.command,
                    "stderr": True,
                    "stdin": False,
                    "stdout": True,
                    "tty": False,
                }
                if args.container:
                    kwargs["container"] = args.container

                response = await core_v1.connect_post_namespaced_pod_exec(
                    **kwargs,
                )
                if isinstance(response, str):
                    output = response
                else:
                    data = getattr(response, "data", "")
                    output = data if isinstance(data, str) else str(data)
                if not output:
                    return "Command completed with no output."
                return output
            finally:
                await ws_client.close()
        except ApiException as exc:
            raise FunctionToolError(
                f"Kubernetes API error ({exc.status}): {exc.reason}"
            ) from None
        except httpx.ConnectError:
            raise FunctionToolError(
                "Failed to connect to Kubernetes cluster. "
                "Check cluster connectivity and credentials."
            ) from None

    return make_tool(k8s_exec, input_model=K8sExecInput)


# ---------------------------------------------------------------------------
# KubernetesToolkit
# ---------------------------------------------------------------------------


class KubernetesToolkit(Toolkit[KubernetesToolkitConfig]):
    """Kubernetes Toolkit execution instance.

    Create tools with per-cluster lightkube AsyncClient and exec ApiClient bound.

    :param config: Kubernetes Toolkit settings
    :param clients: Cluster name to lightkube AsyncClient mapping
    :param exec_clients: Cluster name to kubernetes_asyncio ApiClient mapping for exec
    :param discovery_caches: Cluster name to ResourceDiscoveryCache mapping
    """

    def __init__(
        self,
        *,
        config: KubernetesToolkitConfig,
        clients: dict[str, AsyncClient] | None = None,
        exec_clients: dict[str, ApiClient] | None = None,
        discovery_caches: dict[str, ResourceDiscoveryCache] | None = None,
        credentials: KubernetesCredentials | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self._config = config
        self._clients = clients or {}
        self._exec_clients = exec_clients or {}
        self._discovery_caches = discovery_caches or {}
        self._credentials = credentials
        self._proxy_url = proxy_url
        self._cluster_locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> KubernetesToolkit:
        """Activate only toolkit without starting client load on session enter."""
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Clean up Kubernetes clients on session exit.

        ``kubernetes_asyncio.ApiClient`` owns ``aiohttp.ClientSession``, so if
        not closed, Sentry records ``Unclosed client session`` after session runner
        idle timeout. lightkube client also owns HTTP connection pool, so close it
        together when session-scoped toolkit exits.
        """
        await _close_kubernetes_clients(
            *self._clients.values(),
            *self._exec_clients.values(),
        )

        self._clients.clear()
        self._exec_clients.clear()
        self._discovery_caches.clear()

    def _get_cluster_lock(self, cluster: str) -> asyncio.Lock:
        """Return per-cluster lazy load lock."""
        lock = self._cluster_locks.get(cluster)
        if lock is None:
            lock = asyncio.Lock()
            self._cluster_locks[cluster] = lock
        return lock

    async def _ensure_cluster_clients(self, cluster: str) -> KubernetesClusterClients:
        """Lazy-load cluster client and discovery cache at tool call time."""
        client = self._clients.get(cluster)
        exec_client = self._exec_clients.get(cluster)
        cache = self._discovery_caches.get(cluster)
        if client is not None and exec_client is not None and cache is not None:
            return client, exec_client, cache

        async with self._get_cluster_lock(cluster):
            client = self._clients.get(cluster)
            exec_client = self._exec_clients.get(cluster)
            cache = self._discovery_caches.get(cluster)
            if client is not None and exec_client is not None and cache is not None:
                return client, exec_client, cache

            cluster_config = _get_cluster_config(self._config, cluster)
            if self._credentials is None:
                raise FunctionToolError("Kubernetes toolkit requires credentials.")
            cluster_cred = self._credentials.clusters.get(cluster)
            if cluster_cred is None:
                raise FunctionToolError(
                    f"No Kubernetes credential found for cluster '{cluster}'."
                )

            new_client: AsyncClient | None = None
            new_exec_client: ApiClient | None = None
            try:
                new_client = await create_lightkube_client(
                    cluster_config,
                    cluster_cred,
                    proxy_url=self._proxy_url,
                )
                new_exec_client = await create_exec_api_client(
                    cluster_config,
                    cluster_cred,
                    proxy_url=self._proxy_url,
                )
                httpx_client: httpx.AsyncClient = new_client._client._client  # pyright: ignore[reportPrivateUsage, reportAssignmentType]  # No raw HTTP access method in lightkube public API, so access internal httpx client; runtime is httpx.AsyncClient but stub declares Client
                new_cache = ResourceDiscoveryCache()
                await new_cache.discover(httpx_client)
            except asyncio.CancelledError:
                await _close_kubernetes_clients(new_client, new_exec_client)
                raise
            except _CLIENT_ERRORS as exc:
                await _close_kubernetes_clients(new_client, new_exec_client)
                raise FunctionToolError(
                    f"Failed to initialize Kubernetes cluster '{cluster}': {exc}"
                ) from None
            except Exception as exc:
                await _close_kubernetes_clients(new_client, new_exec_client)
                logger.exception(
                    "Failed to initialize Kubernetes cluster clients",
                    extra={"cluster": cluster},
                )
                raise FunctionToolError(
                    f"Failed to initialize Kubernetes cluster '{cluster}': {exc}"
                ) from None

            self._clients[cluster] = new_client
            self._exec_clients[cluster] = new_exec_client
            self._discovery_caches[cluster] = new_cache
            return new_client, new_exec_client, new_cache

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return tool list and prompt according to settings.

        :param context: Context passed each turn
        :return: Current state (tools + prompt)
        """
        config = self._config
        tools: list[FunctionTool] = [
            _make_list_tool(self._ensure_cluster_clients, config),
            _make_get_tool(self._ensure_cluster_clients, config),
            _make_logs_tool(self._ensure_cluster_clients, config),
            _make_events_tool(self._ensure_cluster_clients, config),
            _make_api_resources_tool(self._ensure_cluster_clients, config),
        ]
        if not config.read_only:
            tools.extend(
                [
                    _make_apply_tool(self._ensure_cluster_clients, config),
                    _make_delete_tool(self._ensure_cluster_clients, config),
                    _make_exec_tool(self._ensure_cluster_clients, config),
                ]
            )

        prompt = self._render_config_prompt()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools, prompt=prompt)

    def _render_config_prompt(self) -> str:
        """Provide connected clusters and security settings as prompt."""
        config = self._config
        cluster_names = [c.name for c in config.clusters]
        parts = [f"Connected clusters: {', '.join(cluster_names)}"]
        if config.read_only:
            parts.append("Mode: read-only")
        else:
            parts.append("Mode: read-write (apply, delete, exec enabled)")
        if config.allowed_namespaces:
            parts.append(f"Allowed namespaces: {', '.join(config.allowed_namespaces)}")
        if config.denied_kinds:
            parts.append(f"Denied resource kinds: {', '.join(config.denied_kinds)}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# KubernetesToolkitProvider
# ---------------------------------------------------------------------------


class KubernetesToolkitProvider(ToolkitProvider[KubernetesToolkitConfig]):
    """Kubernetes Toolkit Provider.

    Native Toolkit based on lightkube + kubernetes_asyncio(exec).
    Create per-cluster lightkube clients and discovery caches at resolve time.
    """

    slug: ClassVar[str] = "kubernetes"
    name: ClassVar[str] = "Kubernetes"
    description: ClassVar[str] = "Kubernetes cluster management"
    system_prompt: ClassVar[str] = dedent("""\
        You have access to Kubernetes cluster management tools.
        Use k8s_list and k8s_get to inspect resources,
        k8s_logs to check pod logs, and k8s_api_resources
        to discover available resource types.
        When specifying resources, use api_version (e.g. "v1",
        "apps/v1") and kind (e.g. "Pod", "Deployment").
        In read-write mode, use k8s_apply to apply YAML manifests,
        k8s_delete to remove resources, and k8s_exec to run
        commands inside pods.
        Use the output_filter parameter (JMESPath expression) on
        k8s_list, k8s_get, and k8s_events to reduce response size
        by projecting only the fields you need.""")
    config_model: ClassVar[type[BaseModel]] = KubernetesToolkitConfig

    async def test_connection(
        self,
        config: KubernetesToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test connection by creating per-cluster lightkube client + namespace lookup.

        :param config: Validated Kubernetes Toolkit settings
        :param credentials_json: Decrypted credentials JSON; no authentication when None
        :param proxy_url: egress proxy URL; direct connection when None
        :return: Connection test result
        """
        if not credentials_json:
            return TestConnectionResult(
                success=False,
                message="No credentials provided",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        try:
            credentials = parse_credentials(credentials_json)
        except (ValidationError, ValueError) as exc:
            return TestConnectionResult(
                success=False,
                message=f"Invalid credentials: {exc}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        results: list[str] = []
        any_failed = False

        for cluster_config in config.clusters:
            cluster_cred = credentials.clusters.get(cluster_config.name)
            if cluster_cred is None:
                results.append(f"{cluster_config.name}: FAILED (no credential)")
                any_failed = True
                continue

            try:
                api_client = await create_exec_api_client(
                    cluster_config,
                    cluster_cred,
                    proxy_url=proxy_url,
                )
            except _CLIENT_ERRORS as exc:
                results.append(f"{cluster_config.name}: FAILED (auth: {exc})")
                any_failed = True
                continue
            except (ValueError, TypeError) as exc:
                results.append(f"{cluster_config.name}: FAILED (config: {exc})")
                any_failed = True
                continue

            try:
                version_info = await VersionApi(api_client).get_code()
                results.append(f"{cluster_config.name}: v{version_info.git_version}")
            except ApiException as exc:
                results.append(
                    f"{cluster_config.name}: FAILED (API {exc.status}: {exc.reason})"
                )
                any_failed = True
            except _CLIENT_ERRORS as exc:
                results.append(f"{cluster_config.name}: FAILED (network: {exc})")
                any_failed = True
            finally:
                await api_client.close()

        detail = ", ".join(results)
        if any_failed:
            return TestConnectionResult(
                success=False,
                message=f"Partial failure: {detail}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        return TestConnectionResult(
            success=True,
            message=f"Connected: {detail}",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )

    async def resolve(
        self,
        config: KubernetesToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[KubernetesToolkitConfig]:
        """Resolve per-cluster credential and create lightkube + exec clients.

        :param config: Validated Kubernetes Toolkit settings
        :param context: Resolve context (credentials, proxy, etc.)
        :return: Credential-bound KubernetesToolkit instance
        """
        credentials = parse_credentials(context.credentials_json)
        return KubernetesToolkit(
            config=config,
            credentials=credentials,
            proxy_url=context.mcp_proxy_url,
        )
