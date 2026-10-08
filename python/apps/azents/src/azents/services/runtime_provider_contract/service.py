"""Runtime management sequencing through completed repository operations."""

import dataclasses
from typing import Annotated, Any

from fastapi import Depends

from azents.repos.runtime_provider_contract_operations import (
    RuntimeProviderContractOperationsRepository,
)
from azents.repos.runtime_provider_policy.data import RuntimeProviderContractRevision


@dataclasses.dataclass
class RuntimeProviderContractService:
    """Sequence completed management operations and postcommit effects."""

    operations: Annotated[
        RuntimeProviderContractOperationsRepository,
        Depends(RuntimeProviderContractOperationsRepository),
    ]

    async def propose_contract(
        self,
        *,
        provider_resource_id: str,
        provider_type: str,
        protocol_version: str,
        contract_payload: dict[str, Any],
    ) -> RuntimeProviderContractRevision:
        """Create or restore the current authenticated Provider capability."""
        return await self.operations.propose_contract(
            provider_resource_id=provider_resource_id,
            provider_type=provider_type,
            protocol_version=protocol_version,
            contract_payload=contract_payload,
        )

    async def list_contracts(
        self,
        provider_logical_id: str,
    ) -> list[RuntimeProviderContractRevision]:
        """List immutable capability advertisement history."""
        return await self.operations.list_contracts(
            provider_logical_id=provider_logical_id
        )
