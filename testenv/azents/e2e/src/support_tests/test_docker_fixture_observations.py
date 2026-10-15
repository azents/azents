"""Listener-free tests of actual Docker fixture decision boundaries."""

import inspect
from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock, Mock

import pytest
from docker.errors import APIError
from pydantic import ValidationError

from support.docker_fixture_observations import (
    DockerWaitObservation,
    decode_docker_network_address,
)
from tests import conftest as e2e_conftest


def _container(monkeypatch: pytest.MonkeyPatch, response: object) -> MagicMock:
    """Replace construction and transport without starting Docker resources."""
    container = MagicMock()
    container.__enter__.return_value = container
    container.get_wrapped_container.return_value.wait.return_value = response
    container.get_logs.return_value = (b"stdout", b"stderr")
    container.with_volume_mapping.return_value = container
    container.with_command.return_value = container
    container.with_kwargs.return_value = container
    monkeypatch.setattr(e2e_conftest, "DockerContainer", Mock(return_value=container))
    monkeypatch.setattr(
        e2e_conftest, "_configure_azents_server_container", Mock(return_value=container)
    )
    return container


def _migrate() -> None:
    """Invoke the real migration fixture with trusted inert collaborators."""
    inspect.unwrap(e2e_conftest.azents_database_schema)(
        container_network=Mock(),
        postgres_container=Mock(),
        rustfs_container=Mock(),
        valkey_container=Mock(),
        rustfs_access_key="access",
        rustfs_secret_key="secret",
        s3_bucket_name="bucket",
        azents_server_image="image",
        auth_jwt_secret_key="jwt",
        credential_encryption_key="encryption",
        system_bootstrap_setup_token="setup",
    )


@pytest.mark.parametrize("operation", ["migration", "cleanup"])
@pytest.mark.parametrize("status", [False, True, "0", None, 0.0])
def test_actual_wait_decisions_reject_malformed_status(
    monkeypatch: pytest.MonkeyPatch, operation: str, status: object
) -> None:
    """Malformed SDK decision fields never count as container exit status."""
    _container(monkeypatch, {"StatusCode": status, "Error": None})
    with pytest.raises(ValidationError):
        if operation == "migration":
            _migrate()
        else:
            e2e_conftest._remove_runtime_provider_data_root("/temporary", image="image")


@pytest.mark.parametrize("operation", ["migration", "cleanup"])
@pytest.mark.parametrize("status", [0, 17, -1, 137])
def test_actual_wait_decisions_preserve_exit_and_log_contracts(
    monkeypatch: pytest.MonkeyPatch, operation: str, status: int
) -> None:
    """Current integer exits retain zero-success and nonzero-failure behavior."""
    container = _container(
        monkeypatch,
        {"StatusCode": status, "Error": None, "future": {"opaque": [None, True]}},
    )
    if status != 0:
        with pytest.raises(pytest.fail.Exception, match="failed"):
            if operation == "migration":
                _migrate()
            else:
                e2e_conftest._remove_runtime_provider_data_root(
                    "/temporary", image="image"
                )
    elif operation == "migration":
        _migrate()
    else:
        e2e_conftest._remove_runtime_provider_data_root("/temporary", image="image")
    container.get_wrapped_container.return_value.wait.assert_called_once_with(
        timeout=120 if operation == "migration" else 30
    )
    assert container.__enter__.call_count == 1
    assert container.__exit__.call_count == 1


@pytest.mark.parametrize("response", [{}, {"StatusCode": None}, None, []])
def test_wait_projection_requires_sdk_status(response: object) -> None:
    """Missing and malformed required data cannot become a success default."""
    with pytest.raises(ValidationError):
        DockerWaitObservation.model_validate(response)


@pytest.mark.parametrize("error", [None, {"Message": "opaque"}, "future"])
def test_wait_projection_ignores_uninterpreted_sdk_error_extensions(
    error: object,
) -> None:
    """Only the exit code controls the current decision, as in the SDK consumer."""
    response = DockerWaitObservation.model_validate({"StatusCode": 0, "Error": error})
    assert response.status_code == 0


@pytest.mark.parametrize("operation", ["migration", "cleanup"])
def test_actual_wait_transport_errors_propagate(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Typed response decoding does not swallow SDK transport failures."""
    container = _container(monkeypatch, {"StatusCode": 0})
    failure = APIError("synthetic transport failure")
    container.get_wrapped_container.return_value.wait.side_effect = failure
    with pytest.raises(APIError) as caught:
        if operation == "migration":
            _migrate()
        else:
            e2e_conftest._remove_runtime_provider_data_root("/temporary", image="image")
    assert caught.value is failure
    assert container.__exit__.call_count == 1


def test_wait_validation_error_hides_raw_input() -> None:
    """Malformed external decision values do not leak into validation text."""
    with pytest.raises(ValidationError) as caught:
        DockerWaitObservation.model_validate(
            {"StatusCode": "private-value", "Error": {"Message": "private-value"}}
        )
    assert "private-value" not in str(caught.value)


def _inspect_data(address: object) -> dict[str, object]:
    """Build inspect evidence with one selected and one opaque network entry."""
    return {
        "NetworkSettings": {
            "Networks": {
                "selected": {"IPAddress": address, "Gateway": None, "future": True},
                "unselected": {"opaque": [None, 1, True]},
            },
            "future": None,
        },
        "Config": {"opaque_credentials": "private"},
    }


class _NetworkCapture(NamedTuple):
    """Typed process and inspect evidence for the actual fixture invocation."""

    popen: Mock
    wrapped: Mock


def _network_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, attributes: object, *, popen: Mock
) -> _NetworkCapture:
    """Invoke the actual control-plane fixture with inert process boundaries."""
    wrapped = Mock()
    wrapped.attrs = attributes
    runtime = Mock()
    runtime.get_wrapped_container.return_value = wrapped
    network = Mock()
    network.name = "selected"
    factory = Mock()
    factory.mktemp.return_value = tmp_path
    bootstrap = Mock()
    bootstrap.access_token = "private-access"
    monkeypatch.setattr(e2e_conftest.subprocess, "Popen", popen)
    monkeypatch.setattr(
        e2e_conftest, "_provider_resource_id", Mock(return_value="resource")
    )
    monkeypatch.setattr(
        e2e_conftest, "issue_runtime_provider_credential", Mock(return_value="private")
    )
    monkeypatch.setattr(
        e2e_conftest, "_wait_for_control_plane_provider_registered", Mock()
    )
    monkeypatch.setattr(e2e_conftest, "_wait_for_runtime_provider_contract", Mock())
    monkeypatch.setattr(
        e2e_conftest, "_create_e2e_strict_network_infrastructure_profile", Mock()
    )
    fixture = inspect.unwrap(e2e_conftest.strict_network_control_plane)(
        tmp_path_factory=factory,
        container_network=network,
        azents_runtime_control_container=runtime,
        azents_public_server_url="http://public.invalid",
        azents_admin_server_url="http://admin.invalid",
        system_bootstrap_evidence=bootstrap,
    )
    try:
        next(fixture)
    finally:
        fixture.close()
    return _NetworkCapture(popen=popen, wrapped=wrapped)


def test_actual_network_fixture_uses_only_selected_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The current explicit network determines the endpoint, never another map entry."""
    popen = Mock()
    capture = _network_fixture(
        monkeypatch, tmp_path, _inspect_data("172.18.0.2"), popen=popen
    )
    wrapped = capture.wrapped
    wrapped.reload.assert_called_once_with()
    command = popen.call_args.args[0]
    assert command[command.index("--endpoint") + 1] == "172.18.0.2:8030"
    assert command[command.index("--network-name") + 1] == "selected"
    assert popen.call_args.kwargs["env"]["AZ_RUNTIME_PROVIDER_CREDENTIAL"] == "private"
    popen.return_value.terminate.assert_called_once_with()
    popen.return_value.wait.assert_called_once_with(timeout=20)


@pytest.mark.parametrize("address", [None, False, 123, 1.5, [], {}])
def test_actual_network_fixture_rejects_malformed_address_before_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, address: object
) -> None:
    """Malformed interpreted inspect fields fail before any simulator is launched."""
    popen = Mock()
    with pytest.raises(ValidationError):
        _network_fixture(monkeypatch, tmp_path, _inspect_data(address), popen=popen)
    popen.assert_not_called()


def test_actual_network_fixture_preserves_empty_address_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty current address keeps the existing unavailable-fixture message."""
    popen = Mock()
    with pytest.raises(pytest.fail.Exception, match="Runtime Control has no address"):
        _network_fixture(monkeypatch, tmp_path, _inspect_data(""), popen=popen)
    popen.assert_not_called()


def test_network_decoder_preserves_missing_selected_network_failure() -> None:
    """Missing selection never falls back to a different known network."""
    with pytest.raises(KeyError, match="missing"):
        decode_docker_network_address(
            _inspect_data("172.18.0.2"), network_name="missing"
        )


@pytest.mark.parametrize(
    "attributes",
    [
        {},
        {"NetworkSettings": None},
        {"NetworkSettings": {}},
        {"NetworkSettings": {"Networks": []}},
        {"NetworkSettings": {"Networks": {"selected": {}}}},
    ],
)
def test_network_decoder_requires_inspect_contract(attributes: object) -> None:
    """Required envelope and selected-address fields remain required at ingress."""
    with pytest.raises(ValidationError) as caught:
        decode_docker_network_address(attributes, network_name="selected")
    assert "input_value" not in str(caught.value)
