"""Gateway test fixtures."""

import io
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from azents_runtime_control.execution_policy import (
    JsonValue,
    RuntimeExecutionPolicy,
    RuntimeExecutionPolicyEnvelope,
    RuntimeExecutionPolicyEvidence,
    canonical_effective_policy_json,
    digest_effective_policy,
    parse_execution_policy_envelope,
)

from azents_container_policy_gateway.config import GatewayConfig


def policy_document(
    *,
    image_build: bool = False,
    container_run: bool = False,
    compose: bool = False,
    bounded_nested_containers: bool = True,
) -> dict[str, JsonValue]:
    """Return one complete policy document."""
    engine = image_build or container_run
    return {
        "schema_version": 1,
        "image_build": {
            "module_id": "container.image_build",
            "version": 1,
            "enabled": image_build,
        },
        "container_run": {
            "module_id": "container.run",
            "version": 1,
            "enabled": container_run,
        },
        "compose": {
            "module_id": "container.compose",
            "version": 1,
            "enabled": compose,
        },
        "resources": {
            "module_id": "container.resources",
            "version": 1,
            "cpu_request_millicores": None,
            "cpu_limit_millicores": 1000 if engine else None,
            "memory_request_bytes": None,
            "memory_limit_bytes": 2_147_483_648 if engine else None,
            "pids": 256 if engine and bounded_nested_containers else None,
            "container_count": (8 if engine and bounded_nested_containers else None),
            "ephemeral_storage_bytes": 10_737_418_240 if engine else None,
            "persistent_storage_bytes": None,
        },
        "engine_storage": {
            "module_id": "engine.storage",
            "version": 1,
            "mode": "ephemeral" if engine else "none",
            "capacity_bytes": 8_589_934_592 if engine else None,
        },
        "network_egress": {
            "module_id": "network.egress",
            "version": 1,
            "mode": "none",
            "allowed_destinations": [],
            "denied_destinations": [],
        },
    }


def policy(
    *,
    image_build: bool = False,
    container_run: bool = False,
    compose: bool = False,
    bounded_nested_containers: bool = True,
) -> RuntimeExecutionPolicy:
    """Return one parsed policy."""
    document = policy_document(
        image_build=image_build,
        container_run=container_run,
        compose=compose,
        bounded_nested_containers=bounded_nested_containers,
    )
    envelope = RuntimeExecutionPolicyEnvelope(
        evidence=RuntimeExecutionPolicyEvidence(
            snapshot_id="snapshot-1",
            digest=digest_effective_policy(document),
            desired_generation=3,
            module_versions={
                "container.image_build": 1,
                "container.run": 1,
                "container.compose": 1,
                "container.resources": 1,
                "engine.storage": 1,
                "network.egress": 1,
            },
            source_versions={
                "profile": 1,
                "workspace": 1,
                "agent": 1,
            },
        ),
        effective_policy_json=canonical_effective_policy_json(document),
    )
    return parse_execution_policy_envelope(envelope, desired_generation=3)


def gateway_env(
    *,
    image_build: bool = False,
    container_run: bool = False,
    compose: bool = False,
    bounded_nested_containers: bool = True,
) -> dict[str, str]:
    """Return complete gateway environment values."""
    document = policy_document(
        image_build=image_build,
        container_run=container_run,
        compose=compose,
        bounded_nested_containers=bounded_nested_containers,
    )
    return {
        "AZ_RUNTIME_ID": "runtime-1",
        "AZ_RUNTIME_EXECUTION_POLICY_DESIRED_GENERATION": "3",
        "AZ_RUNTIME_EXECUTION_POLICY_SNAPSHOT_ID": "snapshot-1",
        "AZ_RUNTIME_EXECUTION_POLICY_DIGEST": digest_effective_policy(document),
        "AZ_RUNTIME_EXECUTION_POLICY_MODULE_VERSIONS": json.dumps(
            {
                "container.image_build": 1,
                "container.run": 1,
                "container.compose": 1,
                "container.resources": 1,
                "engine.storage": 1,
                "network.egress": 1,
            }
        ),
        "AZ_RUNTIME_EXECUTION_POLICY_SOURCE_VERSIONS": json.dumps(
            {
                "profile": 1,
                "workspace": 1,
                "agent": 1,
            }
        ),
        "AZ_RUNTIME_EXECUTION_POLICY_DOCUMENT": canonical_effective_policy_json(
            document
        ),
        "AZ_RUNTIME_GATEWAY_LISTEN_SOCKET": "/tmp/gateway.sock",
        "AZ_RUNTIME_GATEWAY_ENGINE_SOCKET": "/tmp/engine.sock",
    }


@pytest.fixture
def run_policy() -> RuntimeExecutionPolicy:
    """Return a container-run policy."""
    return policy(container_run=True)


@pytest.fixture
def compose_policy() -> RuntimeExecutionPolicy:
    """Return a Compose-enabled policy."""
    return policy(container_run=True, compose=True)


@pytest.fixture
def build_policy() -> RuntimeExecutionPolicy:
    """Return an image-build policy."""
    return policy(image_build=True)


@pytest.fixture
def gateway_config(run_policy: RuntimeExecutionPolicy) -> GatewayConfig:
    """Return one immutable gateway config."""
    return GatewayConfig(
        runtime_id="runtime-1",
        desired_generation=3,
        snapshot_id="snapshot-1",
        policy_digest="d" * 64,
        policy=run_policy,
        public_socket_path=Path("/tmp/gateway.sock"),
        private_engine_socket_path=Path("/tmp/engine.sock"),
    )


@pytest.fixture
def compose_gateway_config(
    compose_policy: RuntimeExecutionPolicy,
) -> GatewayConfig:
    """Return one immutable Compose gateway config."""
    return GatewayConfig(
        runtime_id="runtime-1",
        desired_generation=3,
        snapshot_id="snapshot-1",
        policy_digest="d" * 64,
        policy=compose_policy,
        public_socket_path=Path("/tmp/gateway.sock"),
        private_engine_socket_path=Path("/tmp/engine.sock"),
    )


def json_headers(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return Docker JSON request headers."""
    return {"Content-Type": "application/json", **dict(extra or {})}


def build_context(
    dockerfile: bytes = b"FROM scratch\n",
    *,
    extra_files: Mapping[str, bytes] | None = None,
) -> bytes:
    """Return one bounded local tar build context."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        files = {"Dockerfile": dockerfile, **dict(extra_files or {})}
        for name, contents in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(contents)
            archive.addfile(info, io.BytesIO(contents))
    return output.getvalue()
