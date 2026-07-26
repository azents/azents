"""Immutable gateway configuration and execution-policy loading."""

import dataclasses
import json
import os
from collections.abc import Mapping
from pathlib import Path

from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicy,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    parse_execution_policy_envelope,
)


@dataclasses.dataclass(frozen=True)
class GatewayConfig:
    """Validated immutable gateway process configuration."""

    runtime_id: str
    desired_generation: int
    snapshot_id: str
    policy_digest: str
    policy: RuntimeExecutionPolicy
    public_socket_path: Path
    private_engine_socket_path: Path


def gateway_config_from_env(
    env: Mapping[str, str] | None = None,
) -> GatewayConfig:
    """Load and validate the complete execution-policy envelope before binding."""
    values = os.environ if env is None else env
    runtime_id = _required(values, "AZ_RUNTIME_ID")
    desired_generation = _positive_int(
        _required(values, "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION"),
        "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION",
    )
    snapshot_id = _required(values, "AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID")
    digest = _required(values, "AZ_RUNTIME_EXECUTION_POLICY_DIGEST")
    module_versions = _version_mapping(
        _required(values, "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS"),
        "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS",
    )
    source_versions = _version_mapping(
        _required(values, "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS"),
        "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS",
    )
    document = _policy_document(
        _required(values, "AZ_RUNTIME_EXECUTION_POLICY_DOCUMENT")
    )
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id=snapshot_id,
            digest=digest,
            desired_generation=desired_generation,
            module_versions=module_versions,
            source_versions=source_versions,
        ),
        effective_policy=document,
    )
    policy = parse_execution_policy_envelope(
        envelope,
        desired_generation=desired_generation,
    )
    public_socket_path = _absolute_path(
        _required(values, "AZ_RUNTIME_GATEWAY_LISTEN_SOCKET"),
        "AZ_RUNTIME_GATEWAY_LISTEN_SOCKET",
    )
    private_engine_socket_path = _absolute_path(
        _required(values, "AZ_RUNTIME_GATEWAY_ENGINE_SOCKET"),
        "AZ_RUNTIME_GATEWAY_ENGINE_SOCKET",
    )
    if public_socket_path == private_engine_socket_path:
        raise ValueError("Gateway and private Engine sockets must be different")
    return GatewayConfig(
        runtime_id=runtime_id,
        desired_generation=desired_generation,
        snapshot_id=snapshot_id,
        policy_digest=digest,
        policy=policy,
        public_socket_path=public_socket_path,
        private_engine_socket_path=private_engine_socket_path,
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value:
        raise ValueError(f"{name} is required")
    return value


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _version_mapping(value: str, name: str) -> dict[str, int]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be a JSON object")
    result: dict[str, int] = {}
    for key, item in parsed.items():
        if (
            not isinstance(key, str)
            or not key
            or isinstance(item, bool)
            or not isinstance(item, int)
            or item < 1
        ):
            raise ValueError(f"{name} must map non-empty strings to positive integers")
        result[key] = item
    return result


def _policy_document(value: str) -> dict[str, JsonValue]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("AZ_RUNTIME_EXECUTION_POLICY_DOCUMENT must be a JSON object")
    return {str(key): item for key, item in parsed.items()}


def _absolute_path(value: str, name: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path")
    return path
