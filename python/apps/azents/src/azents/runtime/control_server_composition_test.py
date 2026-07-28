"""Runtime Control transfer composition and shutdown tests."""

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet

import azents.runtime.control_server as control_server
from azents.runtime.control_server import (
    RuntimeControlSettings,
    repair_transfer_once,
    runtime_control_server_lifespan,
    validate_runtime_control_transfer_settings,
)


class _Redis:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class _S3:
    def __init__(self) -> None:
        self.closed = False


class _Coordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def repair_terminal_correlations(self, *, page_size: int) -> int:
        self.calls.append(("terminals", page_size))
        return 4

    async def repair_pending(self, *, page_size: int) -> int:
        self.calls.append(("pending", page_size))
        return 1

    async def reconcile_generations(self, *, page_size: int) -> int:
        self.calls.append(("generations", page_size))
        return 2

    async def repair_stale_stream_claims(
        self, *, cleanup: object, page_size: int
    ) -> int:
        del cleanup
        self.calls.append(("stale", page_size))
        return 3


class _Cleanup:
    pass


def _settings() -> RuntimeControlSettings:
    return RuntimeControlSettings(
        runtime_control_allow_insecure=True,
        runtime_control_port=0,
        runtime_control_transfer_backend="memory",
        runtime_control_workspace_s3_bucket="transfer-bucket",
        runtime_control_workspace_s3_access_key_id="access-key",
        runtime_control_workspace_s3_secret_access_key="secret-key",
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
        runtime_runner_transfer_endpoint="runtime-transfer:8031",
        credential_encryption_key=Fernet.generate_key().decode(),
    )


@pytest.mark.asyncio
async def test_lifespan_composes_all_transfer_services_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One process owns state, S3, repair, and all Runtime Control services."""
    redis = _Redis()
    engine = _Engine()
    s3 = _S3()
    registrations: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(control_server, "create_redis_client", lambda _: redis)
    monkeypatch.setattr(control_server, "_create_engine", lambda _: engine)
    monkeypatch.setattr(
        control_server,
        "add_runtime_provider_control_servicer",
        lambda _server, **kwargs: registrations.append(("provider", kwargs)),
    )
    monkeypatch.setattr(
        control_server,
        "add_runtime_runner_control_servicer",
        lambda _server, **kwargs: registrations.append(("runner", kwargs)),
    )
    monkeypatch.setattr(
        control_server,
        "add_runtime_runner_transfer_servicer",
        lambda _server, **kwargs: registrations.append(("transfer", kwargs)),
    )
    monkeypatch.setattr(
        control_server,
        "add_runtime_transfer_coordinator_servicer",
        lambda _server, **kwargs: registrations.append(("coordinator", kwargs)),
    )

    @asynccontextmanager
    async def s3_service(_: RuntimeControlSettings) -> AsyncIterator[_S3]:
        try:
            yield s3
        finally:
            s3.closed = True

    async def idle(*args: object, stop: asyncio.Event, **kwargs: object) -> None:
        del args, kwargs
        await stop.wait()

    monkeypatch.setattr(control_server, "_runtime_transfer_s3_service", s3_service)
    monkeypatch.setattr(control_server, "_run_reconciler", idle)
    monkeypatch.setattr(control_server, "_run_transfer_repair", idle)

    async with runtime_control_server_lifespan(_settings()):
        names = [name for name, _kwargs in registrations]
        assert names == ["provider", "runner", "transfer", "coordinator"]
        transfer = dict(registrations)["transfer"]
        runner = dict(registrations)["runner"]
        assert transfer["object_store"] is s3
        assert transfer["bucket"] == "transfer-bucket"
        assert transfer["object_prefix"] == "v1/runtime-transfer"
        assert runner["transfer_result_sink"] is not None
        assert "secret-key" not in repr(registrations)

    assert redis.closed
    assert engine.disposed
    assert s3.closed


def test_runtime_control_server_keeps_default_grpc_message_limits() -> None:
    """Transfer composition must not override global gRPC message limits."""
    source = inspect.getsource(control_server.runtime_control_server_lifespan)

    assert "grpc.aio.server()" in source
    assert "max_receive_message_length" not in source
    assert "max_send_message_length" not in source


def test_transfer_settings_reject_unbounded_or_invalid_deployment_values() -> None:
    """Control refuses unsafe transfer bounds before composing services."""
    settings = _settings()
    settings = settings.model_copy(
        update={"runtime_control_transfer_terminal_ttl_seconds": 3_601}
    )

    with pytest.raises(ValueError, match="within 3,600 seconds"):
        validate_runtime_control_transfer_settings(settings)

    settings = _settings().model_copy(
        update={"runtime_control_transfer_multipart_part_bytes": 1}
    )
    with pytest.raises(ValueError, match="at least 5 MiB"):
        validate_runtime_control_transfer_settings(settings)


@pytest.mark.asyncio
async def test_transfer_repair_one_shot_runs_bounded_categories() -> None:
    """One repair pass visits dispatch, generation, and stale-stream work."""
    coordinator = _Coordinator()

    observed = await repair_transfer_once(
        coordinator,  # type: ignore[arg-type]
        cleanup=_Cleanup(),  # type: ignore[arg-type]
        page_size=7,
    )

    assert observed == 10
    assert coordinator.calls == [
        ("terminals", 7),
        ("pending", 7),
        ("generations", 7),
        ("stale", 7),
    ]
