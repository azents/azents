"""Runtime Execution Policy product E2E tests."""

import copy
import time
from urllib.parse import urlsplit

import azentsadminclient
import azentspublicclient
import pytest
import requests
from pydantic import TypeAdapter
from testcontainers.core.container import DockerContainer

from support.runtime_execution_policy import (
    RUNTIME_EXECUTION_LLM_CREDENTIAL_SENTINEL,
    bearer_headers,
    create_runtime_execution_agent_context,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import unique

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_ALWAYS_FORBIDDEN_SAFE_PROJECTION_KEYS = (
    "authorization",
    "credential",
    "secret",
    "token",
)
_NON_NULL_FORBIDDEN_SAFE_PROJECTION_KEYS = (
    "docker_request",
    "manifest",
    "provider_config",
    "service_account",
    "socket",
)


def _json_object(
    response: requests.Response,
    *,
    token: str,
) -> dict[str, object]:
    """Validate one complete JSON response before exposing it to assertions."""
    return _safe_object(response.json(), token=token)


def _request_object(
    method: str,
    url: str,
    *,
    token: str,
    expected_status: int,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    """Issue one authenticated API request and validate its bounded response."""
    response = requests.request(
        method,
        url,
        headers=bearer_headers(token),
        json=body,
        timeout=20,
    )
    if response.status_code != expected_status:
        path = urlsplit(url).path
        raise AssertionError(
            f"{method} {path} returned HTTP {response.status_code}; "
            f"expected HTTP {expected_status}"
        )
    return _json_object(response, token=token)


def _empty_restriction() -> dict[str, object]:
    """Return the complete empty restrictive contribution."""
    return {
        "schema_version": 1,
        "image_build": None,
        "container_run": None,
        "compose": None,
        "resources": None,
        "engine_storage": None,
        "network_egress": None,
    }


def _resource_restriction(cpu_millicores: int) -> dict[str, object]:
    """Return a complete restriction with one finite CPU ceiling."""
    restriction = _empty_restriction()
    restriction["resources"] = {
        "cpu_millicores": cpu_millicores,
        "memory_bytes": None,
        "pids": None,
        "container_count": None,
        "ephemeral_storage_bytes": None,
    }
    return restriction


def _assert_safe_projection(
    value: object,
    *,
    known_sensitive_values: tuple[str, ...],
) -> None:
    """Reject implementation-sensitive or secret-bearing projection keys."""
    if isinstance(value, dict):
        mapping = _JSON_OBJECT.validate_python(value)
        for key, child in mapping.items():
            normalized = key.lower()
            if any(
                part in normalized for part in _ALWAYS_FORBIDDEN_SAFE_PROJECTION_KEYS
            ):
                raise AssertionError(f"unsafe projection key returned: {key}")
            if child is not None and any(
                part in normalized for part in _NON_NULL_FORBIDDEN_SAFE_PROJECTION_KEYS
            ):
                raise AssertionError(f"unsafe projection value returned for key: {key}")
            _assert_safe_projection(
                child,
                known_sensitive_values=known_sensitive_values,
            )
    elif isinstance(value, list):
        for child in TypeAdapter(list[object]).validate_python(value):
            _assert_safe_projection(
                child,
                known_sensitive_values=known_sensitive_values,
            )
    elif isinstance(value, str) and any(
        sensitive_value in value for sensitive_value in known_sensitive_values
    ):
        raise AssertionError("known credential value appeared in a safe projection")


def _known_sensitive_values(token: str) -> tuple[str, str]:
    """Return deterministic sensitive values forbidden from test evidence."""
    return token, RUNTIME_EXECUTION_LLM_CREDENTIAL_SENTINEL


def _safe_object(value: object, *, token: str) -> dict[str, object]:
    """Validate and safety-check one object before field access."""
    parsed = _JSON_OBJECT.validate_python(value)
    _assert_safe_projection(
        parsed,
        known_sensitive_values=_known_sensitive_values(token),
    )
    return parsed


def _runtime_url(
    *,
    public_server_url: str,
    workspace_handle: str,
    agent_id: str,
) -> str:
    """Return the supported Agent Runtime status endpoint."""
    return (
        f"{public_server_url}/agent-runtime/v1/workspaces/{workspace_handle}/"
        f"agents/{agent_id}/runtime"
    )


def _wait_for_runtime_policy(
    *,
    runtime_url: str,
    token: str,
    expected_status: str,
    expected_action: str,
    expected_generation: int | None,
    timeout: float = 120,
) -> dict[str, object]:
    """Wait for one exact server-owned Runtime policy projection."""
    deadline = time.monotonic() + timeout
    last_observed: tuple[object, object, object] | None = None
    while time.monotonic() < deadline:
        runtime = _request_object(
            "GET",
            runtime_url,
            token=token,
            expected_status=200,
        )
        status = _safe_object(runtime["execution_policy"], token=token)
        last_observed = (
            status.get("status"),
            status.get("required_action"),
            status.get("desired_generation"),
        )
        if (
            status["status"] == expected_status
            and status["required_action"] == expected_action
            and (
                expected_generation is None
                or status["desired_generation"] == expected_generation
            )
        ):
            return runtime
        time.sleep(0.25)
    raise AssertionError(
        "Runtime policy projection did not converge to the expected bounded state; "
        f"last observed status/action/generation: {last_observed}"
    )


def _restart_runtime_provider(container: DockerContainer) -> None:
    """Restart the shared Runtime Provider without exposing its logs."""
    marker = "Runtime Provider registered"
    stdout, stderr = container.get_logs()
    previous_count = (
        stdout.decode(errors="replace") + stderr.decode(errors="replace")
    ).count(marker)
    container.start()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if container.get_wrapped_container().status == "exited":
            raise AssertionError("Runtime Provider exited while restarting")
        current_stdout, current_stderr = container.get_logs()
        current_count = (
            current_stdout.decode(errors="replace")
            + current_stderr.decode(errors="replace")
        ).count(marker)
        if current_count > previous_count:
            return
        time.sleep(1)
    raise AssertionError("Runtime Provider did not register after restart")


def _create_standard_profile(
    *,
    admin_server_url: str,
    admin_token: str,
    standard_policy: dict[str, object],
) -> str:
    """Create one ordinary Standard-equivalent Profile through the Admin API."""
    profile_id = f"e2e-standard-{unique()}"
    _request_object(
        "POST",
        f"{admin_server_url}/runtime-execution/v1/profiles",
        token=admin_token,
        expected_status=201,
        body={
            "profile_id": profile_id,
            "display_name": "E2E Standard",
            "description": "Standard-equivalent deterministic E2E Profile.",
            "policy": standard_policy,
        },
    )
    return profile_id


def test_capability_gate_accepts_qualified_typed_policy(
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> None:
    """Reject unknown fields and accept qualified typed engine authority."""
    token = system_bootstrap_evidence.access_token
    platform = _request_object(
        "GET",
        f"{azents_admin_server_url}/runtime-execution/v1/platform-policy",
        token=token,
        expected_status=200,
    )
    capabilities = _JSON_OBJECT.validate_python(platform["capabilities"])
    _assert_safe_projection(
        capabilities,
        known_sensitive_values=_known_sensitive_values(token),
    )
    assert capabilities == {
        "image_build": True,
        "container_run": True,
        "compose": True,
        "storage_modes": ["ephemeral", "none"],
        "network_modes": ["direct", "none"],
    }
    standard_policy = _JSON_OBJECT.validate_python(platform["policy"])

    unknown_policy = copy.deepcopy(standard_policy)
    unknown_policy["raw_provider_field"] = {"kind": "Pod"}
    unknown_response = requests.post(
        f"{azents_admin_server_url}/runtime-execution/v1/profiles",
        headers=bearer_headers(token),
        json={
            "profile_id": f"unknown-module-{unique()}",
            "display_name": "Unknown module",
            "description": "",
            "policy": unknown_policy,
        },
        timeout=20,
    )
    assert unknown_response.status_code == 422
    _json_object(unknown_response, token=token)

    authority_policy = copy.deepcopy(standard_policy)
    image_build = _JSON_OBJECT.validate_python(authority_policy["image_build"])
    image_build["enabled"] = True
    authority_policy["image_build"] = image_build
    authority_policy["resources"] = {
        "module_id": "container.resources",
        "version": 1,
        "cpu_millicores": 1000,
        "memory_bytes": 536870912,
        "pids": 128,
        "container_count": 4,
        "ephemeral_storage_bytes": 1073741824,
    }
    authority_policy["engine_storage"] = {
        "module_id": "engine.storage",
        "version": 1,
        "mode": "ephemeral",
        "capacity_bytes": 1073741824,
    }
    created = _request_object(
        "POST",
        f"{azents_admin_server_url}/runtime-execution/v1/profiles",
        token=token,
        expected_status=201,
        body={
            "profile_id": f"authority-{unique()}",
            "display_name": "Authority request",
            "description": "",
            "policy": authority_policy,
        },
    )
    _assert_safe_projection(
        created,
        known_sensitive_values=_known_sensitive_values(token),
    )
    assert created["policy"] == authority_policy


@pytest.mark.runtime_provider
def test_hierarchy_profile_override_apply_status_and_audit(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Exercise hierarchy, availability, explicit Apply, and safe projections."""
    admin_token = system_bootstrap_evidence.access_token
    platform = _request_object(
        "GET",
        f"{azents_admin_server_url}/runtime-execution/v1/platform-policy",
        token=admin_token,
        expected_status=200,
    )
    standard_policy = _JSON_OBJECT.validate_python(platform["policy"])
    profile_id = _create_standard_profile(
        admin_server_url=azents_admin_server_url,
        admin_token=admin_token,
        standard_policy=standard_policy,
    )
    context = create_runtime_execution_agent_context(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
    )
    runtime_url = _runtime_url(
        public_server_url=azents_public_server_url,
        workspace_handle=context.workspace_handle,
        agent_id=context.agent_id,
    )
    workspace_base = (
        f"{azents_public_server_url}/runtime-execution/v1/workspaces/"
        f"{context.workspace_handle}"
    )
    agent_base = f"{workspace_base}/agents/{context.agent_id}"

    initial_profiles = _request_object(
        "GET",
        f"{workspace_base}/profiles",
        token=context.token,
        expected_status=200,
    )
    initial_items = _JSON_OBJECT_LIST.validate_python(initial_profiles["items"])
    unavailable = next(item for item in initial_items if item["id"] == profile_id)
    assert unavailable["allowed"] is False
    assert unavailable["available"] is False
    assert unavailable["reason"] == "profile_not_allowed"

    workspace = _request_object(
        "GET",
        f"{workspace_base}/policy",
        token=context.token,
        expected_status=200,
    )
    replaced_workspace = _request_object(
        "PUT",
        f"{workspace_base}/policy",
        token=context.token,
        expected_status=200,
        body={
            "expected_version": workspace["version"],
            "restriction": _resource_restriction(1000),
            "allowed_profile_ids": ["system-standard", profile_id],
        },
    )
    assert replaced_workspace["allowed_profile_ids"] == [
        profile_id,
        "system-standard",
    ]
    replaced_workspace_version = replaced_workspace["version"]
    assert isinstance(replaced_workspace_version, int)

    available_profiles = _request_object(
        "GET",
        f"{workspace_base}/profiles",
        token=context.token,
        expected_status=200,
    )
    available_items = _JSON_OBJECT_LIST.validate_python(available_profiles["items"])
    available = next(item for item in available_items if item["id"] == profile_id)
    assert available["allowed"] is True
    assert available["available"] is True
    assert available["reason"] is None

    _request_object(
        "POST",
        f"{runtime_url}/start",
        token=context.token,
        expected_status=200,
    )
    _wait_for_runtime_policy(
        runtime_url=runtime_url,
        token=context.token,
        expected_status="applied",
        expected_action="none",
        expected_generation=None,
    )

    current_agent = _request_object(
        "GET",
        f"{agent_base}/settings",
        token=context.token,
        expected_status=200,
    )
    before_runtime = _request_object(
        "GET",
        runtime_url,
        token=context.token,
        expected_status=200,
    )
    before_raw_runtime = _JSON_OBJECT.validate_python(before_runtime["runtime"])
    before_generation = before_raw_runtime["desired_generation"]
    assert isinstance(before_generation, int)
    before_status = _safe_object(
        before_runtime["execution_policy"],
        token=context.token,
    )
    before_target = _JSON_OBJECT.validate_python(before_status["target"])
    before_applied = _JSON_OBJECT.validate_python(before_status["applied"])
    assert before_status["status"] == "applied"
    assert before_status["required_action"] == "none"
    assert before_target["desired_generation"] == before_generation
    assert before_applied["desired_generation"] == before_generation

    saved = _request_object(
        "PUT",
        f"{agent_base}/settings",
        token=context.token,
        expected_status=200,
        body={
            "expected_version": current_agent["version"],
            "profile_id": profile_id,
            "restriction": _resource_restriction(500),
        },
    )
    assert saved["profile_id"] == profile_id
    preview = _safe_object(saved["effective_preview"], token=context.token)
    assert preview["available"] is True
    reductions = _JSON_OBJECT_LIST.validate_python(preview["reductions"])
    assert any(
        reduction["path"] == "resources.cpu_millicores"
        and reduction["governing_layer"] == "agent"
        for reduction in reductions
    )

    after_save_runtime = _request_object(
        "GET",
        runtime_url,
        token=context.token,
        expected_status=200,
    )
    after_save_raw = _JSON_OBJECT.validate_python(after_save_runtime["runtime"])
    assert after_save_raw["desired_generation"] == before_generation
    configured_status = _safe_object(
        after_save_runtime["execution_policy"],
        token=context.token,
    )
    assert configured_status["status"] == "configured"
    assert configured_status["required_action"] == "apply"
    assert configured_status["desired_generation"] == before_generation
    configured_target = _JSON_OBJECT.validate_python(configured_status["target"])
    configured_applied = _JSON_OBJECT.validate_python(configured_status["applied"])
    assert configured_target["desired_generation"] == before_generation
    assert configured_applied["desired_generation"] == before_generation
    assert configured_target["digest"] == before_target["digest"]
    assert configured_applied["digest"] == before_applied["digest"]
    _assert_safe_projection(
        configured_status,
        known_sensitive_values=_known_sensitive_values(context.token),
    )

    expansion = _request_object(
        "PUT",
        f"{agent_base}/settings",
        token=context.token,
        expected_status=409,
        body={
            "expected_version": saved["version"],
            "profile_id": profile_id,
            "restriction": _resource_restriction(2000),
        },
    )
    _assert_safe_projection(
        expansion,
        known_sensitive_values=_known_sensitive_values(context.token),
    )
    assert expansion == {
        "detail": {
            "code": "execution_policy_expansion_rejected",
            "path": "resources.cpu_millicores",
            "governing_layer": "workspace",
        }
    }

    cleared = _request_object(
        "PUT",
        f"{agent_base}/settings",
        token=context.token,
        expected_status=200,
        body={
            "expected_version": saved["version"],
            "profile_id": profile_id,
            "restriction": _empty_restriction(),
        },
    )
    assert cleared["profile_id"] == profile_id

    applied = _request_object(
        "POST",
        f"{agent_base}/apply",
        token=context.token,
        expected_status=200,
    )
    assert applied["created"] is True
    assert applied["desired_generation"] == before_generation + 1
    assert isinstance(applied["snapshot_id"], str)
    assert isinstance(applied["target_digest"], str)

    applied_runtime = _wait_for_runtime_policy(
        runtime_url=runtime_url,
        token=context.token,
        expected_status="applied",
        expected_action="none",
        expected_generation=before_generation + 1,
    )
    initial_applied_status = _safe_object(
        applied_runtime["execution_policy"],
        token=context.token,
    )
    initial_target = _JSON_OBJECT.validate_python(initial_applied_status["target"])
    assert initial_target["profile_id"] == profile_id
    assert initial_target["storage_mode"] == "none"
    assert initial_target["storage_capacity_bytes"] is None
    assert initial_target["network_mode"] == "none"
    initial_target_digest = initial_target["digest"]
    assert isinstance(initial_target_digest, str)
    _assert_safe_projection(
        initial_applied_status,
        known_sensitive_values=_known_sensitive_values(context.token),
    )

    repeated = _request_object(
        "POST",
        f"{agent_base}/apply",
        token=context.token,
        expected_status=200,
    )
    assert repeated["created"] is False
    assert repeated["snapshot_id"] == applied["snapshot_id"]
    assert repeated["desired_generation"] == applied["desired_generation"]

    runtime_before_tightening = _JSON_OBJECT.validate_python(applied_runtime["runtime"])
    runtime_id = runtime_before_tightening["id"]
    assert isinstance(runtime_id, str)
    azents_runtime_provider_docker_container.stop()
    try:
        tightened_workspace = _request_object(
            "PUT",
            f"{workspace_base}/policy",
            token=context.token,
            expected_status=200,
            body={
                "expected_version": replaced_workspace_version,
                "restriction": _resource_restriction(250),
                "allowed_profile_ids": ["system-standard", profile_id],
            },
        )
        assert tightened_workspace["version"] == replaced_workspace_version + 1

        converging_runtime = _wait_for_runtime_policy(
            runtime_url=runtime_url,
            token=context.token,
            expected_status="pending",
            expected_action="wait",
            expected_generation=before_generation + 2,
        )
        converging_raw = _JSON_OBJECT.validate_python(converging_runtime["runtime"])
        assert converging_raw["id"] == runtime_id
        assert converging_raw["last_lifecycle_command"] == "restart"
        assert converging_raw["reset_final_desired_state"] is None
        converging_status = _safe_object(
            converging_runtime["execution_policy"],
            token=context.token,
        )
        converging_target = _JSON_OBJECT.validate_python(converging_status["target"])
        assert converging_target["desired_generation"] == before_generation + 2
        assert converging_target["digest"] != initial_target_digest
        _assert_safe_projection(
            converging_status,
            known_sensitive_values=_known_sensitive_values(context.token),
        )

        tightened_agent = _request_object(
            "GET",
            f"{agent_base}/settings",
            token=context.token,
            expected_status=200,
        )
        tightened_preview = _safe_object(
            tightened_agent["effective_preview"],
            token=context.token,
        )
        effective_policy = _safe_object(
            tightened_preview["effective_policy"],
            token=context.token,
        )
        effective_resources = _JSON_OBJECT.validate_python(
            effective_policy["resources"]
        )
        assert effective_resources["cpu_millicores"] == 250
        assert (
            _JSON_OBJECT.validate_python(tightened_preview["governing_layers"])[
                "resources.cpu_millicores"
            ]
            == "workspace"
        )
    finally:
        _restart_runtime_provider(azents_runtime_provider_docker_container)

    agent_audit = _request_object(
        "GET",
        f"{agent_base}/audit-events?limit=100",
        token=context.token,
        expected_status=200,
    )
    agent_events = _JSON_OBJECT_LIST.validate_python(agent_audit["items"])
    assert {"agent_settings_replaced", "target_snapshot_attached"} <= {
        event["event_type"] for event in agent_events
    }
    assert any(
        event["event_type"] == "target_snapshot_attached"
        and event["reason_code"] == "automatic_restriction"
        and event["system_authority"] is True
        for event in agent_events
    )
    _assert_safe_projection(
        agent_audit,
        known_sensitive_values=_known_sensitive_values(context.token),
    )

    workspace_audit = _request_object(
        "GET",
        f"{workspace_base}/policy/audit-events?limit=100",
        token=context.token,
        expected_status=200,
    )
    workspace_events = _JSON_OBJECT_LIST.validate_python(workspace_audit["items"])
    assert any(
        event["event_type"] == "workspace_policy_replaced" for event in workspace_events
    )
    _assert_safe_projection(
        workspace_audit,
        known_sensitive_values=_known_sensitive_values(context.token),
    )
