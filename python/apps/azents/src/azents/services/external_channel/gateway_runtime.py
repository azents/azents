"""Provider-neutral runtime for persistent External Channel transports."""

import asyncio
import dataclasses
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayManagerService,
)
from azents.services.external_channel.ingress_recovery import (
    ExternalChannelIngressRecoveryService,
)
from azents.services.external_channel.slack_presence_manager import (
    SlackWorkPresenceManagerService,
)
from azents.services.external_channel.socket_manager import (
    SlackSocketManagerService,
)


class ExternalChannelGatewayManagerStopped(RuntimeError):
    """A required persistent transport manager stopped before shutdown."""


@dataclasses.dataclass
class ExternalChannelGatewayRuntime:
    """Supervise all required persistent External Channel transport managers."""

    slack_socket_manager: Annotated[
        SlackSocketManagerService,
        Depends(SlackSocketManagerService),
    ]
    discord_gateway_manager: Annotated[
        DiscordGatewayManagerService,
        Depends(DiscordGatewayManagerService),
    ]
    slack_presence_manager: Annotated[
        SlackWorkPresenceManagerService,
        Depends(SlackWorkPresenceManagerService),
    ]
    ingress_recovery_service: Annotated[
        ExternalChannelIngressRecoveryService,
        Depends(ExternalChannelIngressRecoveryService),
    ]

    async def run(
        self,
        shutdown_event: asyncio.Event,
        *,
        mark_shutting_down: Callable[[], None],
    ) -> None:
        """Run both transport managers until shutdown or manager failure."""
        if shutdown_event.is_set():
            return

        manager_tasks = {
            "Slack Socket": asyncio.create_task(
                self.slack_socket_manager.run(shutdown_event)
            ),
            "Discord Gateway": asyncio.create_task(
                self.discord_gateway_manager.run(shutdown_event)
            ),
            "Slack Work Presence": asyncio.create_task(
                self.slack_presence_manager.run(shutdown_event)
            ),
            "Ingress Recovery": asyncio.create_task(
                self.ingress_recovery_service.run(shutdown_event)
            ),
        }
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                (*manager_tasks.values(), shutdown_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if shutdown_task in done or shutdown_event.is_set():
                await asyncio.gather(
                    *manager_tasks.values(),
                    return_exceptions=True,
                )
                return

            mark_shutting_down()
            for manager_name, task in manager_tasks.items():
                if task not in done:
                    continue
                try:
                    task.result()
                except asyncio.CancelledError as error:
                    raise ExternalChannelGatewayManagerStopped(
                        f"{manager_name} manager stopped unexpectedly."
                    ) from error
                except Exception as error:
                    raise ExternalChannelGatewayManagerStopped(
                        f"{manager_name} manager stopped unexpectedly."
                    ) from error
                raise ExternalChannelGatewayManagerStopped(
                    f"{manager_name} manager stopped unexpectedly."
                )
            raise AssertionError("Gateway manager wait completed without a result.")
        finally:
            shutdown_event.set()
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)
            await asyncio.gather(
                *manager_tasks.values(),
                return_exceptions=True,
            )
