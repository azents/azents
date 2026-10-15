"""API-only Browser source lifecycle and existing local/TLS provisioning tests."""

import base64
from pathlib import Path

import pytest
from azcommon.logging import RuntimeEnvironment
from azents_runtime_control.grpc_browser_source_client import GrpcBrowserSourceClient
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig

from azents.core.config import (
    Config,
    CredentialEncryptionConfig,
    RuntimeTransferCoordinatorConfig,
)
from azents.core.runtime_browser_source_credential import (
    RuntimeBrowserSourceCredentialSupplier,
)
from azents.runtime.deps import get_api_runtime_browser_source_client
from azents.utils.appctx import AppContext


class _Client:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _config(
    *, endpoint: str | None, local: bool, insecure: bool, ca: Path | None
) -> Config:
    return Config.model_construct(
        runtime_env=RuntimeEnvironment.LOCAL if local else RuntimeEnvironment.DEPLOYED,
        credential_encryption=CredentialEncryptionConfig(
            key=base64.urlsafe_b64encode(b"x" * 32).decode()
        ),
        runtime_transfer_coordinator=RuntimeTransferCoordinatorConfig(
            endpoint=endpoint,
            tls_ca_file=ca,
            allow_insecure=insecure,
            credential_lifetime_seconds=30,
        ),
    )


async def test_browser_client_reuses_process_channel_and_has_browser_only_supplier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ca = tmp_path / "trusted-ca"
    ca.write_bytes(b"synthetic-ca")
    client = _Client()
    captured: dict[str, object] = {}

    def create(endpoint: str, **kwargs: object) -> _Client:
        captured["endpoint"] = endpoint
        captured.update(kwargs)
        return client

    monkeypatch.setattr(GrpcBrowserSourceClient, "from_endpoint", create)
    config = _config(
        endpoint="runtime-control:8030", local=False, insecure=False, ca=ca
    )
    appctx = AppContext(config)
    first = await get_api_runtime_browser_source_client(appctx, config)
    second = await get_api_runtime_browser_source_client(appctx, config)
    assert first is client and second is client
    assert captured["endpoint"] == "runtime-control:8030"
    assert isinstance(
        captured["credential_supplier"], RuntimeBrowserSourceCredentialSupplier
    )
    assert isinstance(captured["tls"], GrpcClientTlsConfig)
    assert captured["allow_insecure"] is False
    await appctx.close()
    assert client.closed


async def test_local_docker_endpoint_uses_explicit_insecure_with_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    captured: dict[str, object] = {}

    def create(endpoint: str, **kwargs: object) -> _Client:
        captured["endpoint"] = endpoint
        captured.update(kwargs)
        return client

    monkeypatch.setattr(GrpcBrowserSourceClient, "from_endpoint", create)
    config = _config(
        endpoint="runtime-control:8030", local=True, insecure=True, ca=None
    )
    appctx = AppContext(config)
    assert await get_api_runtime_browser_source_client(appctx, config) is client
    assert captured["allow_insecure"] is True and captured["tls"] is None
    assert isinstance(
        captured["credential_supplier"], RuntimeBrowserSourceCredentialSupplier
    )
    await appctx.close()


async def test_insecure_transport_is_rejected_outside_local_environment() -> None:
    config = _config(
        endpoint="runtime-control:8030", local=False, insecure=True, ca=None
    )
    appctx = AppContext(config)
    with pytest.raises(ValueError, match="local environments"):
        await get_api_runtime_browser_source_client(appctx, config)
    await appctx.close()


async def test_no_implicit_endpoint_or_local_source_fallback() -> None:
    config = _config(endpoint=None, local=True, insecure=False, ca=None)
    appctx = AppContext(config)
    assert await get_api_runtime_browser_source_client(appctx, config) is None
    await appctx.close()


async def test_missing_tls_trust_does_not_downgrade_to_insecure() -> None:
    config = _config(
        endpoint="runtime-control:8030", local=False, insecure=False, ca=None
    )
    appctx = AppContext(config)
    with pytest.raises(ValueError, match="TLS trust"):
        await get_api_runtime_browser_source_client(appctx, config)
    await appctx.close()
