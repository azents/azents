"""Runtime Control server settings tests."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, Mock

import pytest
from azents_runtime_control.runtime_stream_session import (
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
    RunnerSessionOffer,
)
from cryptography.fernet import Fernet
from pydantic import ValidationError

from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
)
from azents.runtime.control_server import (
    RuntimeControlSettings,
    _owner_offer_blocks_reissue,
    _OwnerRuntimeStreamSessionOfferProvider,
    _RuntimeWebRunnerGenerationGate,
    runtime_control_transport,
    runtime_web_trusted_transport,
    validate_runtime_control_web_settings,
)
from azents.runtime.stream_session_owner import RuntimeStreamSessionOwnerManager


class _ObservedGenerationEvent(asyncio.Event):
    """Expose entry into the real generation wait without scheduler delays."""

    def __init__(self) -> None:
        super().__init__()
        self.wait_entered = asyncio.Event()

    async def wait(self) -> Literal[True]:
        self.wait_entered.set()
        return await super().wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("mark_before_wait", [False, True])
async def test_runner_generation_readiness_remains_available_after_wait(
    mark_before_wait: bool,
) -> None:
    """Owner route acquisition may repeat for the same persisted generation."""
    gate = _RuntimeWebRunnerGenerationGate()
    event = _ObservedGenerationEvent()
    gate.events[("runtime", 3)] = event
    if mark_before_wait:
        await gate.mark(runtime_id="runtime", runner_generation=3)
    waiting = asyncio.create_task(
        gate.wait(runtime_id="runtime", runner_generation=3, timeout_seconds=1)
    )
    try:
        if not mark_before_wait:
            await asyncio.wait_for(event.wait_entered.wait(), timeout=1)
            await gate.mark(runtime_id="runtime", runner_generation=3)
        assert await waiting
        assert await gate.wait(
            runtime_id="runtime", runner_generation=3, timeout_seconds=0
        )
        assert not await gate.wait(
            runtime_id="runtime", runner_generation=4, timeout_seconds=0
        )
        assert not await gate.wait(
            runtime_id="other", runner_generation=3, timeout_seconds=0
        )
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)


@pytest.mark.asyncio
async def test_owner_route_conflict_retains_persisted_generation_readiness(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A live previous Owner lease cannot consume the new generation signal."""
    caplog.set_level(logging.INFO, logger="azents.runtime.control_server")
    gate = _RuntimeWebRunnerGenerationGate()
    event = _ObservedGenerationEvent()
    gate.events[("runtime", 3)] = event
    repository = Mock()
    repository.get_runtime = AsyncMock(
        return_value=Mock(desired_generation=2, runner_generation=3)
    )
    owned = Mock()
    owned.offer = _web_offer(deadline_at=datetime.now(UTC) + timedelta(seconds=5))
    owned.route = Mock(owner_replica_id="owner-replica", lease_generation=1)
    manager = Mock(spec=RuntimeStreamSessionOwnerManager)
    manager.acquire = AsyncMock(
        side_effect=[RuntimeWebSessionRouteConflict("Previous lease is live"), owned]
    )
    provider = _OwnerRuntimeStreamSessionOfferProvider(
        read_repository=repository,
        owner_manager=manager,
        generation_gate=gate,
    )
    first = asyncio.create_task(
        provider.offer_for_runner(runtime_id="runtime", runner_generation=3)
    )
    try:
        await asyncio.wait_for(event.wait_entered.wait(), timeout=1)
        await gate.mark(runtime_id="runtime", runner_generation=3)
        assert await first is None
        assert await gate.wait(
            runtime_id="runtime", runner_generation=3, timeout_seconds=0
        )
        assert (
            await provider.offer_for_runner(runtime_id="runtime", runner_generation=3)
            == owned.offer
        )
        assert manager.acquire.await_count == 2
        assert repository.get_runtime.await_count == 2
        # A fresh acquisition still requires the authoritative generation fence.
        provider.owned.clear()
        repository.get_runtime.return_value = Mock(
            desired_generation=2, runner_generation=4
        )
        assert (
            await provider.offer_for_runner(runtime_id="runtime", runner_generation=3)
            is None
        )
        assert repository.get_runtime.await_count == 3
        assert manager.acquire.await_count == 2
        records = [
            record
            for record in caplog.records
            if record.name == "azents.runtime.control_server"
        ]
        assert [record.message for record in records] == [
            "Runtime Web session offer unavailable",
            "Runtime Web session offer issued",
            "Runtime Web session offer unavailable",
        ]
        assert [record.levelno for record in records] == [
            logging.WARNING,
            logging.INFO,
            logging.WARNING,
        ]
        assert [record.__dict__["runner_generation"] for record in records] == [3, 3, 3]
        assert records[0].__dict__["reason"] == "owner_route_conflict"
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is RuntimeWebSessionRouteConflict
        assert records[1].__dict__["owner_replica_id"] == "owner-replica"
        assert records[1].__dict__["lease_generation"] == 1
        assert records[1].exc_info is None
        assert records[2].__dict__["reason"] == "runner_generation_not_current"
        assert records[2].exc_info is None
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


def _settings() -> RuntimeControlSettings:
    return RuntimeControlSettings(
        runtime_control_allow_insecure=True,
        runtime_runner_image="runner:test",
        runtime_runner_control_endpoint="runtime-control:8030",
        runtime_runner_transfer_endpoint="runtime-transfer:8031",
        credential_encryption_key=Fernet.generate_key().decode(),
    )


def _web_offer(*, deadline_at: datetime) -> RunnerSessionOffer:
    owner = OwnerSessionEpoch(
        owner_boot_id="owner-boot",
        session_lease_id="owner-lease",
        lease_generation=1,
        runtime_id="runtime",
        desired_generation=2,
        runner_generation=3,
    )
    return RunnerSessionOffer(
        owner=owner,
        session_nonce="nonce",
        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
        deadline_at=deadline_at,
    )


def test_joined_owner_offer_blocks_reissue_after_join_deadline() -> None:
    now = datetime(2026, 9, 14, tzinfo=UTC)
    offer = _web_offer(deadline_at=now - timedelta(seconds=1))

    assert _owner_offer_blocks_reissue(
        offer,
        joined={offer.owner},
        runner_generation=3,
        now=now,
    )
    assert not _owner_offer_blocks_reissue(
        offer,
        joined=set(),
        runner_generation=3,
        now=now,
    )
    assert not _owner_offer_blocks_reissue(
        offer,
        joined={offer.owner},
        runner_generation=4,
        now=now,
    )


def test_runtime_control_heartbeat_interval_defaults_to_production_value() -> None:
    assert _settings().testenv_runtime_control_heartbeat_interval_seconds == 20
    assert not _settings().runtime_control_web_transport_enabled


def test_runtime_control_heartbeat_interval_accepts_positive_testenv_override() -> None:
    settings = _settings().model_copy(
        update={"testenv_runtime_control_heartbeat_interval_seconds": 2}
    )

    assert settings.testenv_runtime_control_heartbeat_interval_seconds == 2


def test_runtime_control_heartbeat_interval_rejects_non_positive_value() -> None:
    with pytest.raises(ValidationError):
        RuntimeControlSettings(
            runtime_control_allow_insecure=True,
            runtime_runner_image="runner:test",
            runtime_runner_control_endpoint="runtime-control:8030",
            runtime_runner_transfer_endpoint="runtime-transfer:8031",
            credential_encryption_key=Fernet.generate_key().decode(),
            testenv_runtime_control_heartbeat_interval_seconds=0,
        )


def test_runtime_control_transport_allows_explicit_insecure_mode() -> None:
    """Local/test settings may explicitly select insecure transport."""
    transport = runtime_control_transport(_settings())

    assert transport.server_credentials is None
    assert transport.ca_pem is None
    assert transport.allow_insecure


def test_runtime_control_transport_requires_tls_files() -> None:
    """Deployed secure transport fails closed without operator TLS material."""
    settings = _settings().model_copy(update={"runtime_control_allow_insecure": False})

    with pytest.raises(RuntimeError, match="TLS_CERTIFICATE_FILE"):
        runtime_control_transport(settings)


def test_runtime_control_transport_loads_operator_tls(
    tmp_path: Path,
) -> None:
    """Operator files configure server TLS and the Runner trust bundle."""
    certificate = tmp_path / "tls.crt"
    private_key = tmp_path / "tls.key"
    ca = tmp_path / "ca.crt"
    certificate.write_text("certificate")
    private_key.write_text("private-key")
    ca.write_text("ca-certificate")
    settings = _settings().model_copy(
        update={
            "runtime_control_allow_insecure": False,
            "runtime_control_tls_certificate_file": str(certificate),
            "runtime_control_tls_private_key_file": str(private_key),
            "runtime_control_tls_ca_file": str(ca),
        }
    )

    transport = runtime_control_transport(settings)

    assert transport.server_credentials is not None
    assert transport.ca_pem == "ca-certificate"
    assert not transport.allow_insecure


def test_runtime_web_trusted_transport_isolated_mode_matches_control_security(
    tmp_path: Path,
) -> None:
    """Trusted Gateway/Control traffic requires mutual TLS outside local mode."""
    insecure = runtime_web_trusted_transport(_settings())
    assert insecure.server_credentials is None
    assert insecure.channel_credentials is None
    assert insecure.allow_insecure

    certificate = tmp_path / "tls.crt"
    private_key = tmp_path / "tls.key"
    ca = tmp_path / "ca.crt"
    certificate.write_text("certificate")
    private_key.write_text("private-key")
    ca.write_text("ca-certificate")
    secure = runtime_web_trusted_transport(
        _settings().model_copy(
            update={
                "runtime_control_allow_insecure": False,
                "runtime_control_tls_certificate_file": str(certificate),
                "runtime_control_tls_private_key_file": str(private_key),
                "runtime_control_tls_ca_file": str(ca),
            }
        )
    )

    assert secure.server_credentials is not None
    assert secure.channel_credentials is not None
    assert not secure.allow_insecure


def test_runtime_web_settings_reject_unsafe_owner_leases() -> None:
    """Owner polling remains bounded to the committed revocation window."""
    with pytest.raises(ValueError, match="within 1 to 60 seconds"):
        validate_runtime_control_web_settings(
            _settings().model_copy(
                update={
                    "runtime_control_web_transport_enabled": True,
                    "runtime_control_trusted_advertise_address": "127.0.0.1:8032",
                    "runtime_control_web_route_lease_seconds": 61,
                }
            )
        )

    with pytest.raises(ValueError, match="must be host:port"):
        validate_runtime_control_web_settings(
            _settings().model_copy(
                update={"runtime_control_web_transport_enabled": True}
            )
        )
