"""Runtime Provider contract, configuration, and Runtime policy persistence."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    RuntimeProviderConfigRevisionState,
    RuntimeProviderConfigValidationStatus,
    RuntimeProviderContractStatus,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.runtime_provider import RDBRuntimeProvider
from azents.rdb.models.runtime_provider_policy import (
    RDBAgentRuntimeProviderOverride,
    RDBRuntimePolicySnapshot,
    RDBRuntimeProviderConfigRevision,
    RDBRuntimeProviderContractRevision,
)

from .data import (
    AgentRuntimeProviderOverride,
    RuntimePolicySnapshot,
    RuntimePolicySnapshotCreate,
    RuntimeProviderConfigRevision,
    RuntimeProviderConfigRevisionCreate,
    RuntimeProviderContractRevision,
    RuntimeProviderContractRevisionCreate,
)


class RuntimeProviderPolicyRepository:
    """Persist Provider-scoped policy revisions and immutable Runtime snapshots."""

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

    async def get_contract_by_digest(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        digest: str,
        for_update: bool,
    ) -> RuntimeProviderContractRevision | None:
        """Fetch a contract proposal by its Provider-local semantic digest."""
        statement = sa.select(RDBRuntimeProviderContractRevision).where(
            RDBRuntimeProviderContractRevision.provider_id == provider_id,
            RDBRuntimeProviderContractRevision.digest == digest,
        )
        if for_update:
            statement = statement.with_for_update()
        result = await session.execute(statement)
        rdb = result.scalar_one_or_none()
        return self._build_contract(rdb) if rdb is not None else None

    async def create_contract(
        self,
        session: AsyncSession,
        *,
        create: RuntimeProviderContractRevisionCreate,
    ) -> RuntimeProviderContractRevision:
        """Store one immutable Provider contract revision after the Provider lock."""
        rdb = RDBRuntimeProviderContractRevision(
            provider_id=create.provider_id,
            digest=create.digest,
            implementation_version=create.implementation_version,
            protocol_version=create.protocol_version,
            contract=create.contract,
            compatibility=create.compatibility,
            status=create.status,
            validation_code=create.validation_code,
            validation_message=create.validation_message,
        )
        session.add(rdb)
        await session.flush()
        return self._build_contract(rdb)

    async def accept_contract(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        contract_revision_id: str,
        accepted_by_user_id: str | None,
        accepted_at: datetime.datetime,
    ) -> RuntimeProviderContractRevision | None:
        """Accept one candidate and atomically move the Provider contract pointer."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderContractRevision)
            .where(
                RDBRuntimeProviderContractRevision.id == contract_revision_id,
                RDBRuntimeProviderContractRevision.provider_id == provider_id,
                RDBRuntimeProviderContractRevision.status
                == RuntimeProviderContractStatus.CANDIDATE,
                RDBRuntimeProviderContractRevision.validation_code.is_(None),
            )
            .values(
                status=RuntimeProviderContractStatus.ACCEPTED,
                accepted_by_user_id=accepted_by_user_id,
                accepted_at=accepted_at,
            )
            .returning(RDBRuntimeProviderContractRevision)
        )
        accepted = result.scalar_one_or_none()
        if accepted is None:
            return None
        await session.execute(
            sa.update(RDBRuntimeProviderContractRevision)
            .where(
                RDBRuntimeProviderContractRevision.provider_id == provider_id,
                RDBRuntimeProviderContractRevision.id != contract_revision_id,
                RDBRuntimeProviderContractRevision.status
                == RuntimeProviderContractStatus.ACCEPTED,
            )
            .values(status=RuntimeProviderContractStatus.SUPERSEDED)
        )
        await session.execute(
            sa.update(RDBRuntimeProvider)
            .where(RDBRuntimeProvider.id == provider_id)
            .values(
                accepted_contract_revision_id=contract_revision_id,
                admin_version=RDBRuntimeProvider.admin_version + 1,
            )
        )
        await session.flush()
        return self._build_contract(accepted)

    async def reject_contract(
        self,
        session: AsyncSession,
        *,
        provider_id: str,
        contract_revision_id: str,
        rejected_by_user_id: str | None,
        rejected_at: datetime.datetime,
        validation_code: str,
        validation_message: str,
    ) -> RuntimeProviderContractRevision | None:
        """Reject a pending contract without changing the accepted pointer."""
        result = await session.execute(
            sa.update(RDBRuntimeProviderContractRevision)
            .where(
                RDBRuntimeProviderContractRevision.id == contract_revision_id,
                RDBRuntimeProviderContractRevision.provider_id == provider_id,
                RDBRuntimeProviderContractRevision.status
                == RuntimeProviderContractStatus.CANDIDATE,
            )
            .values(
                status=RuntimeProviderContractStatus.REJECTED,
                validation_code=validation_code,
                validation_message=validation_message,
                rejected_by_user_id=rejected_by_user_id,
                rejected_at=rejected_at,
            )
            .returning(RDBRuntimeProviderContractRevision)
        )
        rdb = result.scalar_one_or_none()
        await session.flush()
        return self._build_contract(rdb) if rdb is not None else None

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
        result = await session.execute(
            sa.update(RDBRuntimeProviderConfigRevision)
            .where(
                RDBRuntimeProviderConfigRevision.id == config_revision_id,
                RDBRuntimeProviderConfigRevision.provider_id == provider_id,
                RDBRuntimeProviderConfigRevision.state
                == RuntimeProviderConfigRevisionState.PROVIDER_ACCEPTED,
                RDBRuntimeProviderConfigRevision.validation_status
                == RuntimeProviderConfigValidationStatus.VALID,
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

    async def get_override(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        provider_id: str,
    ) -> AgentRuntimeProviderOverride | None:
        """Fetch one Agent-scoped override for one Provider."""
        result = await session.execute(
            sa.select(RDBAgentRuntimeProviderOverride).where(
                RDBAgentRuntimeProviderOverride.agent_id == agent_id,
                RDBAgentRuntimeProviderOverride.provider_id == provider_id,
            )
        )
        rdb = result.scalar_one_or_none()
        return self._build_override(rdb) if rdb is not None else None

    async def create_snapshot(
        self,
        session: AsyncSession,
        *,
        create: RuntimePolicySnapshotCreate,
    ) -> RuntimePolicySnapshot | None:
        """Store a snapshot only for the Runtime's immutable Provider binding."""
        rdb = RDBRuntimePolicySnapshot(
            runtime_id=create.runtime_id,
            provider_id=create.provider_id,
            contract_revision_id=create.contract_revision_id,
            config_revision_id=create.config_revision_id,
            override_provider_id=create.override_provider_id,
            override_version=create.override_version,
            resolved_config=create.resolved_config,
            encrypted_secrets=create.encrypted_secrets,
            secret_metadata=create.secret_metadata,
            source_trace=create.source_trace,
            digest=create.digest,
            target_desired_generation=create.target_desired_generation,
            application_state=create.application_state,
        )
        session.add(rdb)
        await session.flush()
        result = await session.execute(
            sa.update(RDBAgentRuntime)
            .where(
                RDBAgentRuntime.id == create.runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == create.provider_id,
                RDBAgentRuntime.runtime_policy_snapshot_id.is_(None),
            )
            .values(runtime_policy_snapshot_id=rdb.id)
            .returning(RDBAgentRuntime.id)
        )
        if result.scalar_one_or_none() is None:
            await session.delete(rdb)
            await session.flush()
            return None
        await session.flush()
        return self._build_snapshot(rdb)

    async def snapshot_matches_runtime_provider(
        self,
        session: AsyncSession,
        *,
        snapshot_id: str,
        runtime_id: str,
        provider_id: str,
    ) -> bool:
        """Check whether reported snapshot belongs to the bound Runtime and Provider."""
        result = await session.execute(
            sa.select(RDBRuntimePolicySnapshot.id).where(
                RDBRuntimePolicySnapshot.id == snapshot_id,
                RDBRuntimePolicySnapshot.runtime_id == runtime_id,
                RDBRuntimePolicySnapshot.provider_id == provider_id,
                RDBAgentRuntime.id == runtime_id,
                RDBAgentRuntime.runtime_provider_resource_id == provider_id,
            )
        )
        return result.scalar_one_or_none() is not None

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
            status=rdb.status,
            validation_code=rdb.validation_code,
            validation_message=rdb.validation_message,
            accepted_by_user_id=rdb.accepted_by_user_id,
            accepted_at=rdb.accepted_at,
            rejected_by_user_id=rdb.rejected_by_user_id,
            rejected_at=rdb.rejected_at,
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

    @staticmethod
    def _build_override(
        rdb: RDBAgentRuntimeProviderOverride,
    ) -> AgentRuntimeProviderOverride:
        return AgentRuntimeProviderOverride(
            agent_id=rdb.agent_id,
            provider_id=rdb.provider_id,
            contract_revision_id=rdb.contract_revision_id,
            version=rdb.version,
            config=rdb.config,
            encrypted_secrets=rdb.encrypted_secrets,
            secret_metadata=rdb.secret_metadata,
            validation_status=rdb.validation_status,
            updated_by_user_id=rdb.updated_by_user_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    @staticmethod
    def _build_snapshot(rdb: RDBRuntimePolicySnapshot) -> RuntimePolicySnapshot:
        return RuntimePolicySnapshot(
            id=rdb.id,
            runtime_id=rdb.runtime_id,
            provider_id=rdb.provider_id,
            contract_revision_id=rdb.contract_revision_id,
            config_revision_id=rdb.config_revision_id,
            override_provider_id=rdb.override_provider_id,
            override_version=rdb.override_version,
            resolved_config=rdb.resolved_config,
            encrypted_secrets=rdb.encrypted_secrets,
            secret_metadata=rdb.secret_metadata,
            source_trace=rdb.source_trace,
            digest=rdb.digest,
            target_desired_generation=rdb.target_desired_generation,
            application_state=rdb.application_state,
            provider_acknowledged_at=rdb.provider_acknowledged_at,
            runtime_observed_at=rdb.runtime_observed_at,
            created_at=rdb.created_at,
        )
