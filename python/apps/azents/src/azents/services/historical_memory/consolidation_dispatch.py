"""Common Session/Run dispatch identity and canonical usage settlement."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable

from azents.core.historical_memory_consolidation import (
    MemoryExecutionAuthorityError,
    MemoryExecutionPrincipal,
)
from azents.engine.events.types import TokenUsagePayload
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
)
from azents.repos.historical_memory_consolidation.execution import (
    MemoryExecutionRepository,
)
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.services.historical_memory.consolidation_model import (
    MemoryExecutionContextPort,
)


@dataclasses.dataclass
class ConsolidationDispatchAdmission:
    """Admit the captured common owner without a second lease or request ledger."""

    principal: MemoryExecutionPrincipal
    repository: MemoryExecutionRepository
    context_port: MemoryExecutionContextPort
    check_stop: Callable[[], Awaitable[bool]]
    settled: bool = dataclasses.field(init=False, default=False)

    async def admit(self) -> None:
        """Observe current domain/common authority immediately before SDK work."""
        if self.settled:
            raise RuntimeError("Memory model dispatch has already been settled.")
        if await self.check_stop():
            raise asyncio.CancelledError("user-stop")
        await self.repository.authorize_execution(self.principal)

    def context(
        self,
        *,
        provider: str,
        integration_id: str,
        model: str,
    ) -> ModelStreamCallContext:
        """Use the real common execution identity on supported provider adapters."""

        async def check_admitted_stop() -> bool:
            try:
                if await self.check_stop():
                    return True
                await self.repository.authorize_execution(self.principal)
            except (
                CanonicalExecutionOwnerGenerationStaleError,
                MemoryExecutionAuthorityError,
            ) as error:
                raise ModelDispatchAdmissionError("ownership") from error
            return False

        return ModelStreamCallContext(
            call_kind="historical_memory",
            provider=provider,
            provider_integration_id=integration_id,
            model=model,
            session_id=self.principal.owner.session_id,
            run_id=self.principal.run_id,
            attempt_number=self.principal.binding.started_turns,
            check_stop=check_admitted_stop,
        )

    async def settle(self, usage: TokenUsagePayload | None) -> None:
        """Complete common scalar usage once without fabricated retry accounting."""
        if self.settled:
            raise RuntimeError("Memory model dispatch has already been settled.")
        await self.context_port.record_usage(self.principal, usage)
        self.settled = True
