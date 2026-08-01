"""Runtime Provider capability and operational configuration persistence."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
)
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_policy import (
    RDBRuntimeProviderConfigRevision,
    RDBRuntimeProviderContractRevision,
)

from .data import (
    RuntimeProviderConfigRevision,
    RuntimeProviderConfigRevisionCreate,
    RuntimeProviderContractRevision,
    RuntimeProviderContractRevisionCreate,
)


class RuntimeProviderPolicyRepository:
    """Persist Provider capability and operational configuration revisions."""

    async def acquire_provider_lock(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
    ) -> bool:
        """Lock a Provider aggregate before changing its policy revisions."""
        result = await session.execute(
            sa.select(RDBRuntimeProvider.id)
            .where(RDBRuntimeProvider.id == provider_id)
            .with_for_update()
        )
        return result.scalar_one_or_none() is not None

    async def get_contract_by_id(
        self,
        session: AsyncSession,
        *,
        contract_revision_id: str,
        for_update: bool,
    ) -> RuntimeProviderContractRevision | None:
        """Fetch one immutable Provider capability contract revision."""
        statement = sa.select(RDBRuntimeProviderContractRevision).where(
            RDBRuntimeProviderContractRevision.id == contract_revision_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_contract(rdb) if rdb is not None else None

    async def list_contracts(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
    ) -> list[RuntimeProviderContractRevision]:
        """List Provider contract revisions from newest to oldest."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderContractRevision)
            .where(RDBRuntimeProviderContractRevision.provider_id == provider_id)
            .order_by(
                RDBRuntimeProviderContractRevision.created_at.desc(),
                RDBRuntimeProviderContractRevision.id.desc(),
            )
        )
        return [self._build_contract(rdb) for rdb in result.scalars()]

    async def create_contract(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderContractRevisionCreate,
    ) -> RuntimeProviderContractRevision:
        """Store and activate one authenticated Provider capability revision."""
        provider_exists = await session.scalar(
            sa.select(RDBRuntimeProvider.id).where(
                RDBRuntimeProvider.id == create.provider_id
            )
        )
        if provider_exists is None:
            raise ValueError("Provider does not exist.")
        rdb = RDBRuntimeProviderContractRevision(
            provider_id=create.provider_id,
            digest=create.digest,
            implementation_version=create.implementation_version,
            protocol_version=create.protocol_version,
            contract=create.contract,
            compatibility=create.compatibility,
        )
        session.add(rdb)
        await session.flush()
        await session.execute(
            sa.update(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.id == create.provider_id)
            .values(
                current_contract_revision_id=rdb.id,
                capabilities=create.contract,
            )
        )
        return self._build_contract(rdb)

    async def get_config_by_id(
        self,
        session: AsyncSession,
        *,
        config_revision_id: str,
        for_update: bool,
    ) -> RuntimeProviderConfigRevision | None:
        """Fetch one immutable Provider configuration revision."""
        statement = sa.select(RDBRuntimeProviderConfigRevision).where(
            RDBRuntimeProviderConfigRevision.id == config_revision_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_config(rdb) if rdb is not None else None

    async def get_active_config(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
    ) -> RuntimeProviderConfigRevision | None:
        """Fetch the configuration revision currently desired for one Provider."""
        result = await session.execute(
            sa.select(RDBRuntimeProviderConfigRevision)
            .join(
                RDBRuntimeProvider,
                RDBRuntimeProvider.active_config_revision_id
                == RDBRuntimeProviderConfigRevision.id,
            )
            .where(RDBRuntimeProvider.id == provider_id)
        )
        rdb = result.scalar_one_or_none()
        return self._build_config(rdb) if rdb is not None else None

    async def create_config_candidate(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderConfigRevisionCreate,
    ) -> RuntimeProviderConfigRevision:
        """Append a candidate revision after the Provider aggregate lock is held."""
        provider = await session.get(RDBRuntimeProvider, create.provider_id)
        if provider is None:
            raise ValueError("Provider does not exist.")
        if provider.current_contract_revision_id != create.contract_revision_id:
            raise ValueError(
                "Configuration candidate must use the Provider's current contract."
            )
        contract = await session.get(
            RDBRuntimeProviderContractRevision,
            create.contract_revision_id,
        )
        if contract is None or contract.provider_id != create.provider_id:
            raise ValueError("Configuration contract does not belong to the Provider.")
        if create.base_revision_id is not None:
            base = await session.get(
                RDBRuntimeProviderConfigRevision,
                create.base_revision_id,
            )
            if base is None or base.provider_id != create.provider_id:
                raise ValueError("Configuration base revision is invalid.")
        latest_result = await session.execute(
            sa.select(sa.func.max(RDBRuntimeProviderConfigRevision.revision)).where(
                RDBRuntimeProviderConfigRevision.provider_id == create.provider_id
            )
        )
        latest = latest_result.scalar_one()
        rdb = RDBRuntimeProviderConfigRevision(
            provider_id=create.provider_id,
            revision=(latest or 0) + 1,
            base_revision_id=create.base_revision_id,
            contract_revision_id=create.contract_revision_id,
            config=create.config,
            encrypted_secrets=create.encrypted_secrets,
            secret_metadata=create.secret_metadata,
            state=RuntimeProviderConfigRevisionState.CANDIDATE,
            validation_status=RuntimeProviderConfigValidationStatus.PENDING,
            validation_request_id=create.validation_request_id,
            created_by_user_id=create.created_by_user_id,
        )
        session.add(rdb)
        await session.flush()
        return self._build_config(rdb)

    async def record_config_validation(
        self,
        session: AsyncSession,
        *,
        config_revision_id: str,
        status: RuntimeProviderConfigValidationStatus,
        validation_code: str | None,
        validation_message: str | None,
        validation_metadata: dict[str, object] | None,
        impact: dict[str, object] | None,
    ) -> RuntimeProviderConfigRevision | None:
        """Record one Provider validation result for the still-pending revision."""
        if status == RuntimeProviderConfigValidationStatus.PENDING:
            raise ValueError("Provider validation must resolve to valid or invalid.")
        next_state = (
            RuntimeProviderConfigRevisionState.PROVIDER_ACCEPTED
            if status == RuntimeProviderConfigValidationStatus.VALID
            else RuntimeProviderConfigRevisionState.REJECTED
        )
        result = await session.execute(
            sa.update(RDBRuntimeProviderConfigRevision)
            .where(
                RDBRuntimeProviderConfigRevision.id == config_revision_id,
                RDBRuntimeProviderConfigRevision.state
                == RuntimeProviderConfigRevisionState.CANDIDATE,
            )
            .values(
                state=next_state,
                validation_status=status,
                validation_code=validation_code,
                validation_message=validation_message,
                validation_metadata=validation_metadata,
                impact=impact,
                updated_at=sa.func.now(),
            )
            .returning(RDBRuntimeProviderConfigRevision)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build_config(rdb) if rdb is not None else None

    async def activate_config(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        config_revision_id: str,
        activated_by_user_id: str | None,
        activated_at: datetime.datetime,
    ) -> RuntimeProviderConfigRevision | None:
        """Make one validated revision active without replacing any Runtime."""
        current_contract_matches = (
            sa.select(sa.literal(1))
            .where(
                RDBRuntimeProvider.id == provider_id,
                RDBRuntimeProvider.current_contract_revision_id
                == RDBRuntimeProviderConfigRevision.contract_revision_id,
            )
            .exists()
        )
        result = await session.execute(
            sa.update(RDBRuntimeProviderConfigRevision)
            .where(
                RDBRuntimeProviderConfigRevision.id == config_revision_id,
                RDBRuntimeProviderConfigRevision.provider_id == provider_id,
                RDBRuntimeProviderConfigRevision.state
                == RuntimeProviderConfigRevisionState.PROVIDER_ACCEPTED,
                RDBRuntimeProviderConfigRevision.validation_status
                == RuntimeProviderConfigValidationStatus.VALID,
                current_contract_matches,
            )
            .values(
                state=RuntimeProviderConfigRevisionState.ACTIVE,
                activated_by_user_id=activated_by_user_id,
                activated_at=activated_at,
                updated_at=activated_at,
            )
            .returning(RDBRuntimeProviderConfigRevision)
        )
        activated = result.scalar_one_or_none()
        if activated is None:
            return None
        await session.execute(
            sa.update(RDBRuntimeProviderConfigRevision)
            .where(
                RDBRuntimeProviderConfigRevision.provider_id == provider_id,
                RDBRuntimeProviderConfigRevision.id != config_revision_id,
                RDBRuntimeProviderConfigRevision.state
                == RuntimeProviderConfigRevisionState.ACTIVE,
            )
            .values(
                state=RuntimeProviderConfigRevisionState.SUPERSEDED,
                updated_at=activated_at,
            )
        )
        await session.execute(
            sa.update(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.id == provider_id)
            .values(
                active_config_revision_id=config_revision_id,
                admin_version=RDBRuntimeProvider.admin_version + 1,
            )
        )
        await session.flush()
        return self._build_config(activated)

    @staticmethod
    def _build_contract(
        rdb: RDBRuntimeProviderContractRevision,
    ) -> RuntimeProviderContractRevision:
        return RuntimeProviderContractRevision(
            id=rdb.id,
            provider_id=rdb.provider_id,
            digest=rdb.digest,
            implementation_version=rdb.implementation_version,
            protocol_version=rdb.protocol_version,
            contract=rdb.contract,
            compatibility=rdb.compatibility,
            created_at=rdb.created_at,
        )

    @staticmethod
    def _build_config(
        rdb: RDBRuntimeProviderConfigRevision,
    ) -> RuntimeProviderConfigRevision:
        return RuntimeProviderConfigRevision(
            id=rdb.id,
            provider_id=rdb.provider_id,
            revision=rdb.revision,
            base_revision_id=rdb.base_revision_id,
            contract_revision_id=rdb.contract_revision_id,
            config=rdb.config,
            encrypted_secrets=rdb.encrypted_secrets,
            secret_metadata=rdb.secret_metadata,
            state=rdb.state,
            validation_status=rdb.validation_status,
            validation_request_id=rdb.validation_request_id,
            validation_code=rdb.validation_code,
            validation_message=rdb.validation_message,
            validation_metadata=rdb.validation_metadata,
            impact=rdb.impact,
            created_by_user_id=rdb.created_by_user_id,
            activated_by_user_id=rdb.activated_by_user_id,
            activated_at=rdb.activated_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
