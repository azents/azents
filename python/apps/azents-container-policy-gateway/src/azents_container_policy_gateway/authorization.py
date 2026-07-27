"""Closed Docker-compatible route and request authorization."""

import dataclasses
import io
import json
import re
import tarfile
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from uuid import uuid4

from azents_runtime_control.execution_policy import RuntimeExecutionPolicy

from azents_container_policy_gateway.compatibility import DOCKER_API_VERSION
from azents_container_policy_gateway.models import (
    AuthorizedEngineRequest,
    GatewayAuthorizationDenied,
)

_MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
_MAX_HEADER_BYTES = 64 * 1024
_MAX_BUILD_CONTEXT_FILES = 10_000
_MAX_QUERY_BYTES = 64 * 1024
_MAX_BUILD_CONTEXT_BYTES = 256 * 1024 * 1024
_GATEWAY_MEMORY_MAX_BYTES = 512 * 1024 * 1024
_CLIENT_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "content-encoding",
        "content-length",
        "content-type",
        "host",
        "transfer-encoding",
        "user-agent",
        "x-azents-correlation-id",
    }
)
_FORWARDED_HEADERS = frozenset({"accept", "content-encoding", "content-type"})
_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "upgrade",
        "x-registry-auth",
        "x-registry-config",
    }
)
_BOOL_QUERY_NAMES = frozenset(
    {
        "all",
        "digests",
        "force",
        "forcerm",
        "follow",
        "link",
        "nocache",
        "noprune",
        "pull",
        "q",
        "rm",
        "size",
        "stderr",
        "stdout",
        "timestamps",
        "v",
        "verbose",
    }
)
_JSON_QUERY_NAMES = frozenset({"buildargs", "filters", "labels"})
_SAFE_PLATFORM_RE = re.compile(r"^linux/(?:amd64|arm64(?:/v8)?)$")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SAFE_SIGNAL_RE = re.compile(r"^(?:[0-9]{1,2}|SIG[A-Z0-9]+)$")
_SAFE_IMAGE_REFERENCE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/-]*(?::[A-Za-z0-9][A-Za-z0-9_.-]*)?"
    r"(?:@sha256:[0-9a-f]{64})?$"
)


@dataclasses.dataclass(frozen=True)
class RouteRule:
    """One fixed method/path/query authorization rule."""

    operation: str
    method: str
    pattern: re.Pattern[str]
    query_names: frozenset[str]
    module: str | None
    body_kind: str


@dataclasses.dataclass(frozen=True)
class ValidatedBody:
    """Sanitized request bytes plus required Runtime-owned resources."""

    body: bytes
    required_containers: tuple[str, ...] = ()
    required_volumes: tuple[str, ...] = ()
    required_networks: tuple[str, ...] = ()
    requested_pids_limit: int | None = None


_ROUTES: tuple[RouteRule, ...] = (
    RouteRule("ping", "GET", re.compile(r"^/_ping$"), frozenset(), None, "empty"),
    RouteRule("version", "GET", re.compile(r"^/version$"), frozenset(), None, "empty"),
    RouteRule("info", "GET", re.compile(r"^/info$"), frozenset(), None, "empty"),
    RouteRule(
        "images.list",
        "GET",
        re.compile(r"^/images/json$"),
        frozenset({"all", "filters", "digests"}),
        "run_or_build",
        "empty",
    ),
    RouteRule(
        "images.inspect",
        "GET",
        re.compile(r"^/images/[^/]+/json$"),
        frozenset(),
        "run_or_build",
        "empty",
    ),
    RouteRule(
        "images.pull",
        "POST",
        re.compile(r"^/images/create$"),
        frozenset({"fromImage", "tag", "platform"}),
        "run_or_build",
        "empty",
    ),
    RouteRule(
        "images.remove",
        "DELETE",
        re.compile(r"^/images/[^/]+$"),
        frozenset({"force", "noprune"}),
        "run_or_build",
        "empty",
    ),
    RouteRule(
        "images.build",
        "POST",
        re.compile(r"^/build$"),
        frozenset(
            {
                "dockerfile",
                "t",
                "q",
                "nocache",
                "pull",
                "rm",
                "forcerm",
                "buildargs",
                "labels",
                "target",
                "platform",
                "version",
                "networkmode",
            }
        ),
        "image_build",
        "build",
    ),
    RouteRule(
        "containers.list",
        "GET",
        re.compile(r"^/containers/json$"),
        frozenset({"all", "limit", "size", "filters"}),
        "container_run",
        "empty",
    ),
    RouteRule(
        "containers.create",
        "POST",
        re.compile(r"^/containers/create$"),
        frozenset({"name", "platform"}),
        "container_run",
        "container_create",
    ),
    RouteRule(
        "containers.inspect",
        "GET",
        re.compile(r"^/containers/[^/]+/json$"),
        frozenset({"size"}),
        "container_run",
        "empty",
    ),
    RouteRule(
        "containers.logs",
        "GET",
        re.compile(r"^/containers/[^/]+/logs$"),
        frozenset(
            {"follow", "stdout", "stderr", "since", "until", "timestamps", "tail"}
        ),
        "container_run",
        "empty",
    ),
    *tuple(
        RouteRule(
            f"containers.{operation}",
            "POST",
            re.compile(rf"^/containers/[^/]+/{operation}$"),
            frozenset(query_names),
            "container_run",
            "empty",
        )
        for operation, query_names in (
            ("start", ("detachKeys",)),
            ("stop", ("t", "signal")),
            ("kill", ("signal",)),
            ("wait", ("condition",)),
        )
    ),
    RouteRule(
        "containers.remove",
        "DELETE",
        re.compile(r"^/containers/[^/]+$"),
        frozenset({"v", "force", "link"}),
        "container_run",
        "empty",
    ),
    RouteRule(
        "events",
        "GET",
        re.compile(r"^/events$"),
        frozenset({"since", "until", "filters"}),
        "compose",
        "empty",
    ),
    RouteRule(
        "networks.list",
        "GET",
        re.compile(r"^/networks$"),
        frozenset({"filters"}),
        "compose",
        "empty",
    ),
    RouteRule(
        "networks.inspect",
        "GET",
        re.compile(r"^/networks/[^/]+$"),
        frozenset({"verbose", "scope"}),
        "compose",
        "empty",
    ),
    RouteRule(
        "networks.create",
        "POST",
        re.compile(r"^/networks/create$"),
        frozenset(),
        "compose",
        "network_create",
    ),
    *tuple(
        RouteRule(
            f"networks.{operation}",
            "POST",
            re.compile(rf"^/networks/[^/]+/{operation}$"),
            frozenset(),
            "compose",
            "network_membership",
        )
        for operation in ("connect", "disconnect")
    ),
    RouteRule(
        "networks.remove",
        "DELETE",
        re.compile(r"^/networks/[^/]+$"),
        frozenset(),
        "compose",
        "empty",
    ),
    RouteRule(
        "volumes.list",
        "GET",
        re.compile(r"^/volumes$"),
        frozenset({"filters"}),
        "compose",
        "empty",
    ),
    RouteRule(
        "volumes.inspect",
        "GET",
        re.compile(r"^/volumes/[^/]+$"),
        frozenset(),
        "compose",
        "empty",
    ),
    RouteRule(
        "volumes.create",
        "POST",
        re.compile(r"^/volumes/create$"),
        frozenset(),
        "compose",
        "volume_create",
    ),
    RouteRule(
        "volumes.remove",
        "DELETE",
        re.compile(r"^/volumes/[^/]+$"),
        frozenset({"force"}),
        "compose",
        "empty",
    ),
)


def authorize_request(
    *,
    policy: RuntimeExecutionPolicy,
    runtime_id: str,
    method: str,
    raw_path: str,
    query: Sequence[tuple[str, str]],
    headers: Mapping[str, str],
    body: bytes,
) -> AuthorizedEngineRequest:
    """Authorize and sanitize one Docker-compatible request."""
    path = _normalized_path(raw_path)
    rule = _route(method, path)
    _authorize_module(policy, rule.module)
    _validate_query(rule, query)
    safe_headers = _validate_headers(rule, headers, body_length=len(body))
    validated_body = _validate_body(
        rule,
        body,
        policy=policy,
        runtime_id=runtime_id,
    )
    correlation_id = headers.get("X-Azents-Correlation-Id") or headers.get(
        "x-azents-correlation-id"
    )
    if correlation_id is None:
        correlation_id = uuid4().hex
    return AuthorizedEngineRequest(
        operation=rule.operation,
        correlation_id=correlation_id,
        method=rule.method,
        path=path,
        query=tuple(query),
        headers=safe_headers,
        body=validated_body.body,
        required_containers=validated_body.required_containers,
        required_volumes=validated_body.required_volumes,
        required_networks=validated_body.required_networks,
        requested_pids_limit=validated_body.requested_pids_limit,
    )


def max_request_bytes(policy: RuntimeExecutionPolicy) -> int:
    """Return the maximum accepted request body size."""
    return max(_MAX_JSON_BODY_BYTES, max_build_context_bytes(policy))


def max_build_context_bytes(policy: RuntimeExecutionPolicy) -> int:
    """Return the policy-bounded local build-context size."""
    ephemeral_bound = policy.resources.ephemeral_storage_bytes
    memory_bound = policy.resources.memory_limit_bytes
    if ephemeral_bound is None or memory_bound is None:
        return _MAX_JSON_BODY_BYTES
    gateway_memory = min(_GATEWAY_MEMORY_MAX_BYTES, memory_bound // 4)
    return max(
        _MAX_JSON_BODY_BYTES,
        min(
            ephemeral_bound,
            gateway_memory // 8,
            _MAX_BUILD_CONTEXT_BYTES,
        ),
    )


def request_body_limit(
    policy: RuntimeExecutionPolicy,
    *,
    method: str,
    raw_path: str,
) -> int:
    """Return the pre-authorization body limit for one fixed route shape."""
    if method == "POST" and raw_path == f"/{DOCKER_API_VERSION}/build":
        return max_build_context_bytes(policy)
    return _MAX_JSON_BODY_BYTES


def _normalized_path(raw_path: str) -> str:
    if "\x00" in raw_path or any(part == ".." for part in raw_path.split("/")):
        raise GatewayAuthorizationDenied(
            "invalid_path",
            "The Docker API path is invalid.",
        )
    if raw_path in {"/_ping", "/version", "/info"}:
        return raw_path
    prefix = f"/{DOCKER_API_VERSION}"
    if not raw_path.startswith(f"{prefix}/"):
        raise GatewayAuthorizationDenied(
            "unsupported_api_version",
            f"Only Docker API {DOCKER_API_VERSION} is supported.",
        )
    return raw_path[len(prefix) :]


def _route(method: str, path: str) -> RouteRule:
    for rule in _ROUTES:
        if rule.method == method and rule.pattern.fullmatch(path):
            return rule
    raise GatewayAuthorizationDenied(
        "unsupported_endpoint",
        "The Docker API endpoint or method is not supported.",
    )


def _authorize_module(
    policy: RuntimeExecutionPolicy,
    module: str | None,
) -> None:
    allowed = (
        module is None
        or (module == "image_build" and policy.image_build)
        or (module == "container_run" and policy.container_run)
        or (module == "compose" and policy.compose)
        or (module == "run_or_build" and (policy.container_run or policy.image_build))
    )
    if not allowed:
        raise GatewayAuthorizationDenied(
            "module_disabled",
            "The execution-policy module required by this operation is disabled.",
        )


def _validate_query(
    rule: RouteRule,
    query: Sequence[tuple[str, str]],
) -> None:
    if sum(len(key) + len(value) for key, value in query) > _MAX_QUERY_BYTES:
        raise GatewayAuthorizationDenied(
            "query_too_large",
            "Docker API query parameters exceed the gateway limit.",
        )
    names = [key for key, _ in query]
    if len(names) != len(set(names)):
        raise GatewayAuthorizationDenied(
            "duplicate_query",
            "Duplicate Docker API query parameters are not supported.",
        )
    unknown = {key for key, _ in query}.difference(rule.query_names)
    if unknown:
        raise GatewayAuthorizationDenied(
            "unsupported_query",
            f"Unsupported query parameters: {', '.join(sorted(unknown))}.",
        )
    values = dict(query)
    for key in _BOOL_QUERY_NAMES.intersection(values):
        if values[key].lower() not in {"0", "1", "false", "true"}:
            raise GatewayAuthorizationDenied(
                "invalid_query",
                f"{key} must be a Docker boolean value.",
            )
    for key in _JSON_QUERY_NAMES.intersection(values):
        _json_query_object(values[key], key)
    platform = values.get("platform")
    if platform is not None and not _SAFE_PLATFORM_RE.fullmatch(platform):
        raise GatewayAuthorizationDenied(
            "platform_denied",
            "Only the fixed Linux execution platforms are supported.",
        )
    if rule.operation == "images.build":
        if values.get("version") not in {None, "1"}:
            raise GatewayAuthorizationDenied(
                "buildkit_session_denied",
                "Only the restricted classic build protocol is supported.",
            )
        if values.get("networkmode") not in {None, "", "default", "none"}:
            raise GatewayAuthorizationDenied(
                "build_network_denied",
                "Build network mode is not permitted.",
            )
        _safe_context_path(values.get("dockerfile", "Dockerfile"), "dockerfile")
        if values.get("dockerfile") not in {None, "Dockerfile"}:
            raise GatewayAuthorizationDenied(
                "build_path_denied",
                "Only the root Dockerfile is supported.",
            )
        image_tag = values.get("t")
        if image_tag is not None and not _SAFE_IMAGE_REFERENCE_RE.fullmatch(image_tag):
            raise GatewayAuthorizationDenied(
                "image_reference_denied",
                "The image reference is invalid.",
            )
    if rule.operation == "images.pull":
        reference = values.get("fromImage")
        if reference is None or not _SAFE_IMAGE_REFERENCE_RE.fullmatch(reference):
            raise GatewayAuthorizationDenied(
                "image_reference_denied",
                "A valid image reference is required.",
            )
    if rule.operation == "containers.create":
        name = values.get("name")
        if name is not None and not _SAFE_NAME_RE.fullmatch(name):
            raise GatewayAuthorizationDenied(
                "container_name_denied",
                "The container name is invalid.",
            )
    if rule.operation == "containers.logs" and values.get("follow", "").lower() in {
        "1",
        "true",
    }:
        raise GatewayAuthorizationDenied(
            "streaming_denied",
            "Unbounded log streaming is not supported.",
        )
    if rule.operation == "containers.kill":
        signal = values.get("signal")
        if signal is not None and not _SAFE_SIGNAL_RE.fullmatch(signal):
            raise GatewayAuthorizationDenied(
                "signal_denied",
                "The container signal is invalid.",
            )


def _validate_headers(
    rule: RouteRule,
    headers: Mapping[str, str],
    *,
    body_length: int,
) -> dict[str, str]:
    if sum(len(key) + len(value) for key, value in headers.items()) > _MAX_HEADER_BYTES:
        raise GatewayAuthorizationDenied(
            "headers_too_large",
            "Request headers exceed the gateway limit.",
        )
    lowered = {key.lower(): value for key, value in headers.items()}
    forbidden = set(lowered).intersection(_FORBIDDEN_HEADERS)
    if forbidden:
        raise GatewayAuthorizationDenied(
            "unsafe_header",
            f"Unsupported headers: {', '.join(sorted(forbidden))}.",
        )
    unknown = set(lowered).difference(_CLIENT_HEADERS)
    if unknown:
        raise GatewayAuthorizationDenied(
            "unsupported_header",
            f"Unsupported headers: {', '.join(sorted(unknown))}.",
        )
    content_length = lowered.get("content-length")
    if content_length is not None and (
        not content_length.isdigit() or int(content_length) != body_length
    ):
        raise GatewayAuthorizationDenied(
            "invalid_content_length",
            "Content-Length does not match the decoded request body.",
        )
    transfer_encoding = lowered.get("transfer-encoding")
    if transfer_encoding is not None and transfer_encoding.lower() != "chunked":
        raise GatewayAuthorizationDenied(
            "unsupported_header",
            "Only HTTP chunked request transfer encoding is supported.",
        )
    correlation_id = lowered.get("x-azents-correlation-id")
    if correlation_id is not None and not _SAFE_NAME_RE.fullmatch(correlation_id):
        raise GatewayAuthorizationDenied(
            "invalid_correlation_id",
            "The correlation identifier is invalid.",
        )
    content_type = lowered.get("content-type", "").split(";", maxsplit=1)[0].strip()
    if (
        rule.body_kind
        in {
            "container_create",
            "network_create",
            "network_membership",
            "volume_create",
        }
        and content_type != "application/json"
    ):
        raise GatewayAuthorizationDenied(
            "unsupported_content_type",
            "This Docker API operation requires application/json.",
        )
    if rule.body_kind == "build" and content_type not in {
        "application/octet-stream",
        "application/x-tar",
    }:
        raise GatewayAuthorizationDenied(
            "unsupported_content_type",
            "A local tar build context is required.",
        )
    content_encoding = lowered.get("content-encoding")
    if content_encoding is not None and (
        rule.body_kind != "build" or content_encoding.lower() not in {"gzip", "x-gzip"}
    ):
        raise GatewayAuthorizationDenied(
            "unsupported_content_encoding",
            "The request content encoding is not supported.",
        )
    return {key: value for key, value in lowered.items() if key in _FORWARDED_HEADERS}


def _validate_body(
    rule: RouteRule,
    body: bytes,
    *,
    policy: RuntimeExecutionPolicy,
    runtime_id: str,
) -> ValidatedBody:
    if rule.body_kind == "empty":
        if body:
            raise GatewayAuthorizationDenied(
                "unexpected_body",
                "This Docker API operation does not accept a request body.",
            )
        return ValidatedBody(body=b"")
    if rule.body_kind == "build":
        if not body:
            raise GatewayAuthorizationDenied(
                "build_context_required",
                "A local build context is required.",
            )
        if len(body) > max_build_context_bytes(policy):
            raise GatewayAuthorizationDenied(
                "build_context_too_large",
                "The build context exceeds the execution-policy limit.",
            )
        _validate_build_context(body, max_bytes=max_build_context_bytes(policy))
        return ValidatedBody(body=body)
    if len(body) > _MAX_JSON_BODY_BYTES:
        raise GatewayAuthorizationDenied(
            "json_body_too_large",
            "The Docker API request body exceeds the gateway limit.",
        )
    try:
        value = json.loads(body or b"{}")
    except json.JSONDecodeError as error:
        raise GatewayAuthorizationDenied(
            "invalid_json",
            "The Docker API request body must be valid JSON.",
        ) from error
    if not isinstance(value, dict):
        raise GatewayAuthorizationDenied(
            "invalid_json",
            "The Docker API request body must be a JSON object.",
        )
    if rule.body_kind == "container_create":
        sanitized = _container_create(value, policy=policy, runtime_id=runtime_id)
    elif rule.body_kind == "network_create":
        sanitized = _network_create(value, runtime_id=runtime_id)
    elif rule.body_kind == "network_membership":
        sanitized = _network_membership(value)
    elif rule.body_kind == "volume_create":
        sanitized = _volume_create(value, runtime_id=runtime_id)
    else:
        raise AssertionError(f"unsupported gateway body kind: {rule.body_kind}")
    encoded = json.dumps(sanitized, separators=(",", ":")).encode()
    if rule.body_kind == "network_membership":
        container = sanitized.get("Container")
        if not isinstance(container, str):
            raise AssertionError("validated network membership has no container")
        return ValidatedBody(
            body=encoded,
            required_containers=(container,),
        )
    if rule.body_kind != "container_create":
        return ValidatedBody(body=encoded)
    return ValidatedBody(
        body=encoded,
        required_volumes=_required_named_volumes(sanitized),
        required_networks=_required_networks(sanitized),
        requested_pids_limit=_pids_limit(sanitized),
    )


def _container_create(
    value: dict[str, object],
    *,
    policy: RuntimeExecutionPolicy,
    runtime_id: str,
) -> dict[str, object]:
    allowed_top = {
        "Hostname",
        "Domainname",
        "Image",
        "Cmd",
        "Entrypoint",
        "Env",
        "WorkingDir",
        "User",
        "Labels",
        "Healthcheck",
        "ArgsEscaped",
        "Volumes",
        "NetworkDisabled",
        "MacAddress",
        "OnBuild",
        "Shell",
        "AttachStdin",
        "ExposedPorts",
        "AttachStdout",
        "AttachStderr",
        "Tty",
        "OpenStdin",
        "StdinOnce",
        "StopSignal",
        "StopTimeout",
        "HostConfig",
        "NetworkingConfig",
    }
    _reject_unknown_fields(value, allowed_top, "container")
    inert_fields = {
        "Hostname",
        "Domainname",
        "ArgsEscaped",
        "Volumes",
        "NetworkDisabled",
        "MacAddress",
        "OnBuild",
        "Shell",
        "AttachStdin",
    }
    for field in inert_fields:
        if _has_authority(value.get(field)):
            raise GatewayAuthorizationDenied(
                "unsafe_container_field",
                f"{field} is not permitted.",
            )
    _validate_boolean_fields(
        value,
        {
            "AttachStdin",
            "AttachStdout",
            "AttachStderr",
            "Tty",
            "OpenStdin",
            "StdinOnce",
            "NetworkDisabled",
        },
        "container",
    )
    image = value.get("Image")
    if (
        not isinstance(image, str)
        or not image
        or not _SAFE_IMAGE_REFERENCE_RE.fullmatch(image)
    ):
        raise GatewayAuthorizationDenied(
            "image_required",
            "A valid container image reference is required.",
        )
    sanitized = {
        key: item
        for key, item in value.items()
        if key != "HostConfig" and key not in inert_fields
    }
    labels = _string_mapping(value.get("Labels"), "container labels")
    labels["azents/runtime-id"] = runtime_id
    labels["azents/execution-policy-managed"] = "true"
    sanitized["Labels"] = labels
    sanitized["HostConfig"] = _host_config(
        value.get("HostConfig"),
        policy=policy,
    )
    networking = value.get("NetworkingConfig")
    if networking is not None:
        sanitized["NetworkingConfig"] = _networking_config(
            networking,
            compose=policy.compose,
        )
    return sanitized


def _host_config(
    value: object,
    *,
    policy: RuntimeExecutionPolicy,
) -> dict[str, object]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise GatewayAuthorizationDenied(
            "invalid_host_config",
            "HostConfig must be a JSON object.",
        )
    always_denied = {
        "Binds",
        "CapAdd",
        "ContainerIDFile",
        "Annotations",
        "Devices",
        "DeviceRequests",
        "PidMode",
        "IpcMode",
        "UTSMode",
        "CgroupnsMode",
        "UsernsMode",
        "Runtime",
        "SecurityOpt",
        "Sysctls",
        "Dns",
        "DnsOptions",
        "DnsSearch",
        "ExtraHosts",
        "PortBindings",
        "VolumesFrom",
        "Tmpfs",
        "CgroupParent",
        "DeviceCgroupRules",
        "Ulimits",
        "Links",
        "GroupAdd",
        "StorageOpt",
        "VolumeDriver",
        "ReadonlyPaths",
        "MaskedPaths",
        "Cgroup",
        "OomScoreAdj",
        "Isolation",
        "CpuShares",
        "BlkioWeight",
        "BlkioWeightDevice",
        "BlkioDeviceReadBps",
        "BlkioDeviceWriteBps",
        "BlkioDeviceReadIOps",
        "BlkioDeviceWriteIOps",
        "CpuPeriod",
        "CpuQuota",
        "CpuRealtimePeriod",
        "CpuRealtimeRuntime",
        "CpusetCpus",
        "CpusetMems",
        "KernelMemory",
        "KernelMemoryTCP",
        "MemoryReservation",
        "MemorySwap",
        "MemorySwappiness",
        "OomKillDisable",
        "CpuCount",
        "CpuPercent",
        "IOMaximumIOps",
        "IOMaximumBandwidth",
    }
    for field in always_denied:
        field_value = value.get(field)
        if field == "MemorySwappiness" and field_value == -1:
            continue
        if _has_authority(field_value):
            raise GatewayAuthorizationDenied(
                "unsafe_container_field",
                f"HostConfig.{field} is not permitted.",
            )
    if value.get("Privileged") is True or value.get("PublishAllPorts") is True:
        raise GatewayAuthorizationDenied(
            "unsafe_container_field",
            "Privileged mode and published host ports are not permitted.",
        )
    console_size = value.get("ConsoleSize")
    if console_size is not None and console_size != [0, 0]:
        raise GatewayAuthorizationDenied(
            "unsafe_container_field",
            "HostConfig.ConsoleSize is not permitted.",
        )
    network_mode = value.get("NetworkMode")
    if network_mode in {"host"} or (
        isinstance(network_mode, str) and network_mode.startswith("container:")
    ):
        raise GatewayAuthorizationDenied(
            "unsafe_network_mode",
            "Host and container namespace network modes are not permitted.",
        )
    allowed = {
        "AutoRemove",
        "ReadonlyRootfs",
        "RestartPolicy",
        "ShmSize",
        "Memory",
        "NanoCpus",
        "PidsLimit",
        "CapDrop",
        "NetworkMode",
        "Mounts",
        "LogConfig",
        "Init",
        "ConsoleSize",
    }
    _reject_unknown_fields(
        value,
        allowed | always_denied | {"Privileged", "PublishAllPorts"},
        "HostConfig",
    )
    sanitized = {
        key: item
        for key, item in value.items()
        if key in allowed and key != "ConsoleSize"
    }
    _validate_boolean_fields(
        sanitized,
        {"AutoRemove", "ReadonlyRootfs", "Init"},
        "HostConfig",
    )
    _validate_resource_ceiling(
        sanitized.get("NanoCpus"),
        None
        if policy.resources.cpu_limit_millicores is None
        else policy.resources.cpu_limit_millicores * 1_000_000,
        "NanoCpus",
    )
    _validate_resource_ceiling(
        sanitized.get("Memory"),
        policy.resources.memory_limit_bytes,
        "Memory",
    )
    pids_limit = _normalized_pids_limit(
        sanitized.get("PidsLimit"),
        policy=policy,
    )
    if pids_limit is None:
        sanitized.pop("PidsLimit", None)
    else:
        sanitized["PidsLimit"] = pids_limit
    shm_size = sanitized.get("ShmSize")
    if shm_size is not None:
        _validate_resource_ceiling(
            shm_size,
            policy.resources.memory_limit_bytes,
            "ShmSize",
        )
    mounts = sanitized.get("Mounts")
    if mounts is not None:
        sanitized["Mounts"] = _named_volume_mounts(mounts)
    restart_policy = sanitized.get("RestartPolicy")
    if restart_policy is not None:
        sanitized["RestartPolicy"] = _restart_policy(restart_policy)
    log_config = sanitized.get("LogConfig")
    if log_config is not None:
        sanitized["LogConfig"] = _log_config(log_config)
    return sanitized


def _networking_config(value: object, *, compose: bool) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GatewayAuthorizationDenied(
            "invalid_networking_config",
            "NetworkingConfig must be a JSON object.",
        )
    _reject_unknown_fields(value, {"EndpointsConfig"}, "NetworkingConfig")
    endpoints = value.get("EndpointsConfig")
    if endpoints is None:
        return {}
    if endpoints == {}:
        return {}
    if not compose or not isinstance(endpoints, dict):
        raise GatewayAuthorizationDenied(
            "compose_network_denied",
            "Compose-managed network endpoints are not permitted.",
        )
    sanitized: dict[str, object] = {}
    for name, endpoint in endpoints.items():
        if not isinstance(name, str) or not name or not isinstance(endpoint, dict):
            raise GatewayAuthorizationDenied(
                "invalid_networking_config",
                "Network endpoint configuration is invalid.",
            )
        sanitized[name] = _network_endpoint(endpoint)
    return {"EndpointsConfig": sanitized}


def _named_volume_mounts(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise GatewayAuthorizationDenied(
            "invalid_mounts",
            "HostConfig.Mounts must be a JSON array.",
        )
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise GatewayAuthorizationDenied(
                "invalid_mounts",
                "Each mount must be a JSON object.",
            )
        _reject_unknown_fields(
            item,
            {"Type", "Source", "Target", "ReadOnly", "VolumeOptions"},
            "mount",
        )
        if item.get("Type") != "volume":
            raise GatewayAuthorizationDenied(
                "bind_mount_denied",
                "Only Engine-owned named volumes are permitted.",
            )
        source = item.get("Source")
        target = item.get("Target")
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(target, str)
            or not target.startswith("/")
        ):
            raise GatewayAuthorizationDenied(
                "invalid_mounts",
                "Named volume source and absolute target are required.",
            )
        volume_options = item.get("VolumeOptions")
        if volume_options is not None:
            if not isinstance(volume_options, dict):
                raise GatewayAuthorizationDenied(
                    "invalid_mounts",
                    "VolumeOptions must be a JSON object.",
                )
            _reject_unknown_fields(
                volume_options,
                {"NoCopy", "Subpath", "DriverConfig"},
                "volume options",
            )
            if _has_authority(volume_options.get("DriverConfig")):
                raise GatewayAuthorizationDenied(
                    "volume_driver_denied",
                    "Named volume driver configuration is not permitted.",
                )
        result.append(item)
    return result


def _network_create(value: dict[str, object], *, runtime_id: str) -> dict[str, object]:
    _reject_unknown_fields(
        value,
        {
            "Name",
            "Driver",
            "Scope",
            "EnableIPv4",
            "EnableIPv6",
            "IPAM",
            "Internal",
            "Attachable",
            "Ingress",
            "ConfigOnly",
            "ConfigFrom",
            "Options",
            "Labels",
            "CheckDuplicate",
        },
        "network",
    )
    if value.get("Driver") not in {None, "", "bridge"}:
        raise GatewayAuthorizationDenied(
            "network_driver_denied",
            "Only the Engine bridge network driver is permitted.",
        )
    if value.get("Ingress") is True or value.get("ConfigOnly") is True:
        raise GatewayAuthorizationDenied(
            "network_mode_denied",
            "Ingress and config-only networks are not permitted.",
        )
    _validate_boolean_fields(
        value,
        {
            "EnableIPv4",
            "EnableIPv6",
            "Internal",
            "Attachable",
            "Ingress",
            "ConfigOnly",
            "CheckDuplicate",
        },
        "network",
    )
    scope = value.get("Scope")
    if scope not in {None, "", "local"}:
        raise GatewayAuthorizationDenied(
            "network_scope_denied",
            "Only local Engine networks are permitted.",
        )
    if value.get("EnableIPv4") is False or value.get("EnableIPv6") is True:
        raise GatewayAuthorizationDenied(
            "network_protocol_denied",
            "Custom network protocol enablement is not permitted.",
        )
    for field in ("IPAM", "ConfigFrom", "Options"):
        if _has_authority(value.get(field)):
            raise GatewayAuthorizationDenied(
                "network_configuration_denied",
                f"Network {field} is not permitted.",
            )
    name = value.get("Name")
    if not isinstance(name, str) or not _SAFE_NAME_RE.fullmatch(name):
        raise GatewayAuthorizationDenied(
            "network_name_required",
            "A valid named network is required.",
        )
    labels = _string_mapping(value.get("Labels"), "network labels")
    labels["azents/runtime-id"] = runtime_id
    return {
        "Name": name,
        "Driver": "bridge",
        "Internal": value.get("Internal", False),
        "Attachable": value.get("Attachable", False),
        "Labels": labels,
    }


def _network_membership(value: dict[str, object]) -> dict[str, object]:
    _reject_unknown_fields(
        value,
        {"Container", "Force", "EndpointConfig"},
        "network membership",
    )
    container = value.get("Container")
    if not isinstance(container, str) or not _SAFE_NAME_RE.fullmatch(container):
        raise GatewayAuthorizationDenied(
            "container_name_required",
            "A valid Runtime-owned container is required.",
        )
    endpoint = value.get("EndpointConfig")
    if endpoint is not None:
        if not isinstance(endpoint, dict):
            raise GatewayAuthorizationDenied(
                "invalid_networking_config",
                "EndpointConfig must be a JSON object.",
            )
        endpoint = _network_endpoint(endpoint)
    force = value.get("Force", False)
    if not isinstance(force, bool):
        raise GatewayAuthorizationDenied(
            "invalid_boolean_field",
            "Network membership Force must be boolean.",
        )
    return {
        "Container": container,
        "Force": force,
        **({"EndpointConfig": endpoint} if endpoint is not None else {}),
    }


def _volume_create(value: dict[str, object], *, runtime_id: str) -> dict[str, object]:
    _reject_unknown_fields(value, {"Name", "Driver", "Labels"}, "volume")
    if value.get("Driver") not in {None, "", "local"}:
        raise GatewayAuthorizationDenied(
            "volume_driver_denied",
            "Only the local Engine volume driver is permitted.",
        )
    name = value.get("Name")
    if not isinstance(name, str) or not _SAFE_NAME_RE.fullmatch(name):
        raise GatewayAuthorizationDenied(
            "volume_name_required",
            "A valid named volume is required.",
        )
    labels = _string_mapping(value.get("Labels"), "volume labels")
    labels["azents/runtime-id"] = runtime_id
    return {**value, "Driver": "local", "Labels": labels}


def _validate_resource_ceiling(
    value: object,
    ceiling: int | None,
    name: str,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise GatewayAuthorizationDenied(
            "resource_limit_exceeded",
            f"{name} exceeds the execution-policy ceiling.",
        )
    if value == 0:
        return
    if value < 1 or (ceiling is not None and value > ceiling):
        raise GatewayAuthorizationDenied(
            "resource_limit_exceeded",
            f"{name} exceeds the execution-policy ceiling.",
        )


def _normalized_pids_limit(
    value: object,
    *,
    policy: RuntimeExecutionPolicy,
) -> int | None:
    ceiling = policy.resources.pids
    container_count = policy.resources.container_count
    if value is None:
        if ceiling is None:
            return None
        return max(1, ceiling // container_count) if container_count else ceiling
    if isinstance(value, bool) or not isinstance(value, int):
        raise GatewayAuthorizationDenied(
            "resource_limit_exceeded",
            "PidsLimit exceeds the execution-policy ceiling.",
        )
    if value in {0, -1}:
        if ceiling is None:
            return None
        return max(1, ceiling // container_count) if container_count else ceiling
    if value < 1 or (ceiling is not None and value > ceiling):
        raise GatewayAuthorizationDenied(
            "resource_limit_exceeded",
            "PidsLimit exceeds the execution-policy ceiling.",
        )
    return value


def _reject_unknown_fields(
    value: Mapping[str, object],
    allowed: set[str],
    location: str,
) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise GatewayAuthorizationDenied(
            "unsupported_field",
            f"Unsupported {location} fields: {', '.join(sorted(unknown))}.",
        )


def _validate_boolean_fields(
    value: Mapping[str, object],
    fields: set[str],
    location: str,
) -> None:
    invalid = sorted(
        field
        for field in fields
        if field in value
        and value[field] is not None
        and not isinstance(value[field], bool)
    )
    if invalid:
        raise GatewayAuthorizationDenied(
            "invalid_boolean_field",
            f"{location} fields must be boolean: {', '.join(invalid)}.",
        )


def _string_mapping(value: object, location: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise GatewayAuthorizationDenied(
            "invalid_labels",
            f"{location} must map strings to strings.",
        )
    return {str(key): str(item) for key, item in value.items()}


def _has_authority(value: object) -> bool:
    return (
        value is not None
        and value is not False
        and value != ""
        and value != 0
        and value != []
        and value != {}
    )


def _network_endpoint(value: Mapping[str, object]) -> dict[str, object]:
    allowed = {
        "IPAMConfig",
        "Links",
        "Aliases",
        "MacAddress",
        "DriverOpts",
        "GwPriority",
        "NetworkID",
        "EndpointID",
        "Gateway",
        "IPAddress",
        "IPPrefixLen",
        "IPv6Gateway",
        "GlobalIPv6Address",
        "GlobalIPv6PrefixLen",
        "DNSNames",
    }
    _reject_unknown_fields(value, allowed, "network endpoint")
    for field in allowed.difference({"Aliases", "DNSNames"}):
        if _has_authority(value.get(field)):
            raise GatewayAuthorizationDenied(
                "static_network_configuration_denied",
                f"Network endpoint {field} is not permitted.",
            )
    result: dict[str, object] = {}
    for field in ("Aliases", "DNSNames"):
        names = value.get(field)
        if names is None:
            continue
        if not isinstance(names, list) or any(
            not isinstance(name, str) or not _SAFE_NAME_RE.fullmatch(name)
            for name in names
        ):
            raise GatewayAuthorizationDenied(
                "invalid_networking_config",
                f"Network endpoint {field} must contain safe names.",
            )
        result[field] = names
    return result


def _json_query_object(value: str, name: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise GatewayAuthorizationDenied(
            "invalid_query",
            f"{name} must be a JSON object.",
        ) from error
    if not isinstance(parsed, dict):
        raise GatewayAuthorizationDenied(
            "invalid_query",
            f"{name} must be a JSON object.",
        )
    return parsed


def _safe_context_path(
    value: str,
    name: str,
    *,
    allow_root: bool = False,
) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or value == ""
        or (not allow_root and path == PurePosixPath("."))
    ):
        raise GatewayAuthorizationDenied(
            "build_path_denied",
            f"{name} must be a relative build-context path.",
        )
    return path


def _validate_build_context(body: bytes, *, max_bytes: int) -> None:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(body), mode="r:*")
    except (tarfile.TarError, OSError) as error:
        raise GatewayAuthorizationDenied(
            "invalid_build_context",
            "The local build context must be a valid tar archive.",
        ) from error
    total_bytes = 0
    dockerfile_present = False
    try:
        for count, member in enumerate(archive, start=1):
            if count > _MAX_BUILD_CONTEXT_FILES:
                raise GatewayAuthorizationDenied(
                    "build_context_too_many_files",
                    "The build context contains too many entries.",
                )
            path = _safe_context_path(
                member.name,
                "build context entry",
                allow_root=True,
            )
            if member.isdev() or member.isfifo():
                raise GatewayAuthorizationDenied(
                    "build_context_special_file_denied",
                    "Build contexts cannot contain device or FIFO entries.",
                )
            if member.issym() or member.islnk():
                _safe_context_path(member.linkname, "build context link")
            total_bytes += member.size
            if total_bytes > max_bytes:
                raise GatewayAuthorizationDenied(
                    "build_context_too_large",
                    "The expanded build context exceeds the execution-policy limit.",
                )
            if str(path) == "Dockerfile" and member.isfile():
                dockerfile_present = True
    finally:
        archive.close()
    if not dockerfile_present:
        raise GatewayAuthorizationDenied(
            "dockerfile_required",
            "The local build context must contain Dockerfile.",
        )


def _required_named_volumes(value: Mapping[str, object]) -> tuple[str, ...]:
    host_config = value.get("HostConfig")
    if not isinstance(host_config, dict):
        return ()
    mounts = host_config.get("Mounts")
    if not isinstance(mounts, list):
        return ()
    result: list[str] = []
    for item in mounts:
        if not isinstance(item, dict):
            continue
        source = item.get("Source")
        if isinstance(source, str):
            result.append(source)
    return tuple(result)


def _pids_limit(value: Mapping[str, object]) -> int | None:
    host_config = value.get("HostConfig")
    if not isinstance(host_config, dict):
        return None
    pids_limit = host_config.get("PidsLimit")
    if isinstance(pids_limit, bool) or not isinstance(pids_limit, int):
        return None
    return pids_limit


def _required_networks(value: Mapping[str, object]) -> tuple[str, ...]:
    result: set[str] = set()
    host_config = value.get("HostConfig")
    if isinstance(host_config, dict):
        network_mode = host_config.get("NetworkMode")
        if isinstance(network_mode, str) and network_mode not in {
            "",
            "bridge",
            "default",
            "none",
        }:
            result.add(network_mode)
    networking = value.get("NetworkingConfig")
    if isinstance(networking, dict):
        endpoints = networking.get("EndpointsConfig")
        if isinstance(endpoints, dict):
            result.update(str(name) for name in endpoints)
    return tuple(sorted(result))


def _restart_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GatewayAuthorizationDenied(
            "invalid_restart_policy",
            "RestartPolicy must be a JSON object.",
        )
    _reject_unknown_fields(value, {"Name", "MaximumRetryCount"}, "restart policy")
    if value.get("Name") not in {None, "", "no", "on-failure"}:
        raise GatewayAuthorizationDenied(
            "restart_policy_denied",
            "Only no and bounded on-failure restart policies are permitted.",
        )
    retries = value.get("MaximumRetryCount")
    if retries is not None and (
        isinstance(retries, bool)
        or not isinstance(retries, int)
        or not 0 <= retries <= 10
    ):
        raise GatewayAuthorizationDenied(
            "restart_policy_denied",
            "RestartPolicy.MaximumRetryCount must be between zero and ten.",
        )
    return value


def _log_config(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise GatewayAuthorizationDenied(
            "invalid_log_config",
            "LogConfig must be a JSON object.",
        )
    _reject_unknown_fields(value, {"Type", "Config"}, "log configuration")
    if value.get("Type") not in {None, "", "json-file", "local"}:
        raise GatewayAuthorizationDenied(
            "log_driver_denied",
            "Only local Engine log drivers are permitted.",
        )
    config = value.get("Config")
    if config is not None:
        if not isinstance(config, dict) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in config.items()
        ):
            raise GatewayAuthorizationDenied(
                "invalid_log_config",
                "LogConfig.Config must map strings to strings.",
            )
        if set(config).difference({"max-file", "max-size"}):
            raise GatewayAuthorizationDenied(
                "log_driver_denied",
                "Only bounded local log options are permitted.",
            )
    return value
