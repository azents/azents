"""Persistent External Channel gateway runtime tests."""

import asyncio
from typing import cast

import pytest

from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayManagerService,
)
from azents.services.external_channel.gateway_runtime import (
    ExternalChannelGatewayManagerStopped,
    ExternalChannelGatewayRuntime,
)
from azents.services.external_channel.ingress_recovery import (
    ExternalChannelIngressRecoveryService,
)
from azents.services.external_channel.socket_manager import (
    SlackSocketManagerService,
)


class _WaitingManager:
    """Track one manager lifecycle around the shared shutdown event."""

    def __init__(self, *, lifecycle: list[str] | None = None) -> None:
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()
        self.lifecycle = lifecycle

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Wait until gateway shutdown."""
        self.started.set()
        await shutdown_event.wait()
        if self.lifecycle is not None:
            self.lifecycle.append("manager_stopped")
        self.stopped.set()


class _ReturningManager:
    """Return immediately instead of supervising connections."""

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Return before shutdown."""
        del shutdown_event


class _FailingManager:
    """Raise one deterministic manager failure."""

    async def run(self, shutdown_event: asyncio.Event) -> None:
        """Fail before shutdown."""
        del shutdown_event
        raise ValueError("manager failure")


def _runtime(
    *,
    slack_manager: object,
    discord_manager: object,
) -> ExternalChannelGatewayRuntime:
    return ExternalChannelGatewayRuntime(
        slack_socket_manager=cast(SlackSocketManagerService, slack_manager),
        discord_gateway_manager=cast(
            DiscordGatewayManagerService,
            discord_manager,
        ),
        ingress_recovery_service=cast(
            ExternalChannelIngressRecoveryService,
            _WaitingManager(),
        ),
    )


@pytest.mark.asyncio
async def test_runtime_runs_both_managers_until_shutdown() -> None:
    """All required producer loops share one graceful shutdown event."""
    slack_manager = _WaitingManager()
    discord_manager = _WaitingManager()
    shutdown_event = asyncio.Event()
    task = asyncio.create_task(
        _runtime(
            slack_manager=slack_manager,
            discord_manager=discord_manager,
        ).run(shutdown_event, mark_shutting_down=lambda: None)
    )

    await asyncio.gather(
        slack_manager.started.wait(),
        discord_manager.started.wait(),
    )
    shutdown_event.set()
    await task

    assert slack_manager.stopped.is_set()
    assert discord_manager.stopped.is_set()


@pytest.mark.asyncio
async def test_runtime_fails_when_required_manager_returns() -> None:
    """A missing transport class terminates the combined runtime."""
    lifecycle: list[str] = []
    sibling_manager = _WaitingManager(lifecycle=lifecycle)

    with pytest.raises(
        ExternalChannelGatewayManagerStopped,
        match="Slack Socket manager stopped unexpectedly",
    ):
        await _runtime(
            slack_manager=_ReturningManager(),
            discord_manager=sibling_manager,
        ).run(
            asyncio.Event(),
            mark_shutting_down=lambda: lifecycle.append("readiness_stopped"),
        )

    assert sibling_manager.stopped.is_set()
    assert lifecycle == ["readiness_stopped", "manager_stopped"]


@pytest.mark.asyncio
async def test_runtime_wraps_required_manager_failure() -> None:
    """Manager errors retain their cause while stopping the sibling manager."""
    sibling_manager = _WaitingManager()

    with pytest.raises(
        ExternalChannelGatewayManagerStopped,
        match="Discord Gateway manager stopped unexpectedly",
    ) as raised:
        await _runtime(
            slack_manager=sibling_manager,
            discord_manager=_FailingManager(),
        ).run(asyncio.Event(), mark_shutting_down=lambda: None)

    assert isinstance(raised.value.__cause__, ValueError)
    assert sibling_manager.stopped.is_set()
