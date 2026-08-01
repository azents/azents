"""Runtime Provider capability advertisement and revision history."""

import dataclasses
from typing import Annotated, Any

from azcommon.datetime import tznow
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.runtime_profile import RuntimeReconcileSourceKind
from azents.core.runtime_provider_contract import (
    RuntimeProviderCapabilityContract,
    canonicalize_runtime_provider_contract,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.runtime_provider.repository import RuntimeProviderRepository
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderContractRevision,
    RuntimeProviderContractRevisionCreate,
)
from azents.repos.runtime_provider_policy.repository import (
    RuntimeProviderPolicyRepository,
)


@dataclasses.dataclass
class RuntimeProviderContractUnavailable(Exception):
    """A Provider contract operation cannot be completed safely."""

    code: str
    message: str
    current_admin_version: int | None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)


@dataclasses.dataclass
class RuntimeProviderContractService:
    """Persist authenticated Provider advertisements as current authority."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    provider_repository: Annotated[
        RuntimeProviderRepository, Depends(RuntimeProviderRepository)
    ]
    policy_repository: Annotated[
        RuntimeProviderPolicyRepository, Depends(RuntimeProviderPolicyRepository)
    ]
    profile_repository: Annotated[
        RuntimeProfileRepository, Depends(RuntimeProfileRepository)
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
        try:
            contract = RuntimeProviderCapabilityContract.model_validate(
                contract_payload
            )
        except ValidationError as error:
            raise RuntimeProviderContractUnavailable(
                code="contract_invalid",
                message="Provider capability contract is invalid.",
                current_admin_version=None,
            ) from error
        if (
            contract.implementation_key != provider_type
            or contract.protocol_version != protocol_version
        ):
            raise RuntimeProviderContractUnavailable(
                code="contract_identity_mismatch",
                message=(
                    "Provider capability contract identity does not match registration."
                ),
                current_admin_version=None,
            )
        canonical = canonicalize_runtime_provider_contract(contract)
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_id(
                session,
                provider_id=provider_resource_id,
                for_update=True,
            )
            if provider is None:
                raise RuntimeProviderContractUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                    current_admin_version=None,
                )
            if provider.kind.value != provider_type:
                raise RuntimeProviderContractUnavailable(
                    code="contract_identity_mismatch",
                    message=(
                        "Provider capability contract identity does not match the "
                        "durable Provider."
                    ),
                    current_admin_version=provider.admin_version,
                )
            if provider.current_contract_revision_id is not None:
                current = await self.policy_repository.get_contract_by_id(
                    session,
                    contract_revision_id=provider.current_contract_revision_id,
                    for_update=False,
                )
                if current is not None and current.digest == canonical.digest:
                    return current
            revision = await self.policy_repository.create_contract(
                session,
                create=RuntimeProviderContractRevisionCreate(
                    provider_id=provider.id,
                    digest=canonical.digest,
                    implementation_version=contract.implementation_version,
                    protocol_version=contract.protocol_version,
                    contract=canonical.canonical_json,
                    compatibility={"compatible": True},
                ),
            )
            await self.profile_repository.enqueue_reconcile_task(
                session,
                source_type=RuntimeReconcileSourceKind.PROVIDER_CAPABILITY,
                source_id=provider.id,
                source_version=revision.id,
                available_at=tznow(),
            )
            return revision

    async def list_contracts(
        self,
        provider_logical_id: str,
    ) -> list[RuntimeProviderContractRevision]:
        """List immutable capability advertisement history."""
        async with self.session_manager() as session:
            provider = await self.provider_repository.get_by_provider_id(
                session,
                provider_logical_id=provider_logical_id,
                for_update=False,
            )
            if provider is None:
                raise RuntimeProviderContractUnavailable(
                    code="provider_not_found",
                    message="Runtime Provider was not found.",
                    current_admin_version=None,
                )
            return await self.policy_repository.list_contracts(
                session,
                provider_id=provider.id,
            )
