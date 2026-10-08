"""Trusted Runtime Provider bootstrap source orchestration."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.runtime_provider_bootstrap import (
    RuntimeProviderBootstrapReconcileResult,
    RuntimeProviderBootstrapSnapshot,
    RuntimeProviderBootstrapSourceError,
)
from azents.repos.runtime_provider_bootstrap_operations import (
    RuntimeProviderBootstrapOperations,
)


@dataclasses.dataclass(frozen=True)
class RuntimeProviderBootstrapService:
    """Sequence completed reconciliation without receiving database sessions."""

    operations: Annotated[
        RuntimeProviderBootstrapOperations, Depends(RuntimeProviderBootstrapOperations)
    ]

    async def reconcile(
        self, snapshot: RuntimeProviderBootstrapSnapshot
    ) -> RuntimeProviderBootstrapReconcileResult:
        """Reconcile one already validated source through its atomic DB operation."""
        return await self.operations.reconcile(snapshot)

    async def record_source_error(
        self, source_error: RuntimeProviderBootstrapSourceError
    ) -> None:
        """Record a sanitized adapter failure without withdrawing declarations."""
        await self.operations.record_source_error(source_error)
