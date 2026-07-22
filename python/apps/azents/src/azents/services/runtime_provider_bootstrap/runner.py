"""Runtime Provider bootstrap source polling lifecycle."""

import asyncio
import dataclasses
import logging
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import Depends

from azents.core.config import RuntimeProviderBootstrapConfig
from azents.core.deps import get_runtime_provider_bootstrap_config
from azents.core.enums import RuntimeProviderBootstrapAdapterKind

from .data import RuntimeProviderBootstrapSourceError
from .helm_file import (
    HelmFileRuntimeProviderBootstrapAdapter,
    RuntimeProviderBootstrapSourceDocumentError,
)
from .service import RuntimeProviderBootstrapService

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class RuntimeProviderBootstrapRunner:
    """Poll one configured trusted source for authoritative snapshots."""

    config: Annotated[
        RuntimeProviderBootstrapConfig,
        Depends(get_runtime_provider_bootstrap_config),
    ]
    service: Annotated[RuntimeProviderBootstrapService, Depends()]
    _last_successful_revision: tuple[str, str] | None = dataclasses.field(
        init=False,
        default=None,
    )

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Run bootstrap reconciliation for the owning process lifespan."""
        if not self.config.enabled:
            yield
            return
        await self._run_iteration()
        task = asyncio.create_task(
            self._poll(),
            name="runtime-provider-bootstrap",
        )
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def reconcile_once(self) -> None:
        """Read and reconcile the configured source once."""
        source_key = self.config.source_key
        source_path = self.config.source_path
        if source_key is None or source_path is None:
            return
        adapter = HelmFileRuntimeProviderBootstrapAdapter(
            source_key=source_key,
            path=source_path,
        )
        try:
            snapshot = await adapter.read_snapshot()
        except RuntimeProviderBootstrapSourceDocumentError as error:
            await self.service.record_source_error(
                RuntimeProviderBootstrapSourceError(
                    source_key=error.source_key,
                    adapter_kind=RuntimeProviderBootstrapAdapterKind.HELM_FILE,
                    error_code=error.code,
                    error_message=str(error),
                )
            )
            logger.warning(
                "Runtime Provider bootstrap source rejected",
                extra={
                    "source_key": error.source_key,
                    "error_code": error.code,
                },
            )
            return
        revision = (snapshot.source_revision, snapshot.source_digest)
        if revision == self._last_successful_revision:
            return
        result = await self.service.reconcile(snapshot)
        self._last_successful_revision = revision
        logger.info(
            "Runtime Provider bootstrap source reconciled",
            extra={
                "source_key": snapshot.source_key,
                "source_revision": snapshot.source_revision,
                "created_provider_count": len(result.created_provider_ids),
                "reconciled_provider_count": len(result.reconciled_provider_ids),
                "withdrawn_provider_count": len(result.withdrawn_provider_ids),
                "conflict_count": len(result.conflicted_declaration_keys),
            },
        )

    async def _poll(self) -> None:
        while True:
            await asyncio.sleep(self.config.poll_interval_seconds)
            await self._run_iteration()

    async def _run_iteration(self) -> None:
        try:
            await self.reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Runtime Provider bootstrap reconciliation failed")
