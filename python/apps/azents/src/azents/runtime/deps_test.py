"""Runtime dependency composition tests."""

import base64
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from azents_runtime_control.grpc_transfer_coordinator_client import (
    GrpcRuntimeTransferCoordinatorClient,
)

from azents.core.config import (
    Config,
    CredentialEncryptionConfig,
    RuntimeTransferCoordinatorConfig,
)
from azents.runtime.deps import (
    get_api_runtime_transfer_coordinator_client,
    get_worker_runtime_transfer_coordinator_client,
)
from azents.utils.appctx import AppContext


class _FakeCoordinatorClient:
    """Track one owned Coordinator client lifecycle."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        """Record AppContext shutdown."""
        self.closed = True


def _config(
    *,
    endpoint: str | None,
    tls_ca_file: Path | None,
    allow_insecure: bool = False,
) -> Config:
    return cast(
        Config,
        SimpleNamespace(
            credential_encryption=CredentialEncryptionConfig(
                key=base64.urlsafe_b64encode(b"x" * 32).decode("ascii")
            ),
            runtime_transfer_coordinator=RuntimeTransferCoordinatorConfig(
                endpoint=endpoint,
                tls_ca_file=tls_ca_file,
                allow_insecure=allow_insecure,
                credential_lifetime_seconds=30,
            ),
        ),
    )


async def test_worker_coordinator_client_uses_tls_and_worker_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Worker client owns one TLS channel and scopes credentials to Worker identity."""
    trust_bundle = tmp_path / "ca.crt"
    trust_bundle.write_bytes(b"test-ca")
    client = _FakeCoordinatorClient()
    captured: dict[str, object] = {}

    def create_client(*args: object, **kwargs: object) -> _FakeCoordinatorClient:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return client

    monkeypatch.setattr(
        GrpcRuntimeTransferCoordinatorClient,
        "from_endpoint",
        create_client,
    )
    config = _config(endpoint="runtime-control:8030", tls_ca_file=trust_bundle)
    appctx = AppContext(config)

    first = await get_worker_runtime_transfer_coordinator_client(appctx, config)
    second = await get_worker_runtime_transfer_coordinator_client(appctx, config)

    assert first is client
    assert second is client
    args = cast(tuple[object, ...], captured["args"])
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert args == ("runtime-control:8030",)
    assert kwargs["allow_insecure"] is False
    assert kwargs["tls"].root_certificates == b"test-ca"  # type: ignore[union-attr]
    assert kwargs["credential_supplier"].service_identity == "azents-worker"  # type: ignore[union-attr]

    await appctx.close()

    assert client.closed


async def test_api_coordinator_client_uses_explicit_api_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API clients use a different credential identity from Worker clients."""
    client = _FakeCoordinatorClient()
    captured: dict[str, object] = {}

    def create_client(*args: object, **kwargs: object) -> _FakeCoordinatorClient:
        del args
        captured.update(kwargs)
        return client

    monkeypatch.setattr(
        GrpcRuntimeTransferCoordinatorClient,
        "from_endpoint",
        create_client,
    )
    config = _config(
        endpoint="runtime-control:8030",
        tls_ca_file=None,
        allow_insecure=True,
    )
    appctx = AppContext(config)

    result = await get_api_runtime_transfer_coordinator_client(appctx, config)

    assert result is client
    assert captured["tls"] is None
    assert captured["allow_insecure"] is True
    assert captured["credential_supplier"].service_identity == "azents-api"  # type: ignore[union-attr]

    await appctx.close()


async def test_coordinator_client_is_absent_without_cutover_configuration() -> None:
    """A non-cutover process has no implicit local transfer replacement."""
    config = _config(endpoint=None, tls_ca_file=None)
    appctx = AppContext(config)

    assert await get_worker_runtime_transfer_coordinator_client(appctx, config) is None

    await appctx.close()


async def test_coordinator_client_rejects_missing_tls_trust() -> None:
    """A configured secure endpoint fails closed without a trust bundle."""
    config = _config(endpoint="runtime-control:8030", tls_ca_file=None)
    appctx = AppContext(config)

    with pytest.raises(ValueError, match="TLS trust is required"):
        await get_worker_runtime_transfer_coordinator_client(appctx, config)

    await appctx.close()
