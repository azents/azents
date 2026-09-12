"""Repository-owned Runtime Web authority operations."""

import datetime
import hashlib

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebCycle,
    RDBRuntimeWebEndpoint,
    RDBRuntimeWebOperationReceipt,
    RDBRuntimeWebQuotaScope,
    RDBRuntimeWebRequest,
    RuntimeWebCycleEndReason,
    RuntimeWebOperationKind,
    RuntimeWebQuotaScopeKind,
    RuntimeWebRequesterKind,
    RuntimeWebRequestState,
)
from azents.repos.runtime_web.data import (
    RuntimeWebConfiguration,
    RuntimeWebCycle,
    RuntimeWebEndpoint,
    RuntimeWebMutationResult,
    RuntimeWebOperationIdentity,
    RuntimeWebRequest,
    derived_operation_key,
)


class RuntimeWebRepositoryConflict(ValueError):
    """The expected Runtime Web authority changed."""


class RuntimeWebRepositoryQuotaExceeded(ValueError):
    """A logical Runtime Web quota is exhausted."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


class RuntimeWebRepository:
    """Durable Runtime Web authority repository."""

    async def get_configuration(
        self,
        session: AsyncSession,
    ) -> RuntimeWebConfiguration | None:
        """Load current durable configuration."""
        rdb = await session.get(RDBRuntimeWebAuthConfiguration, 1)
        if rdb is None:
            return None
        return RuntimeWebConfiguration(
            enabled=rdb.enabled,
            mode=rdb.mode,
            configuration_version=rdb.configuration_version,
            fingerprint=rdb.fingerprint,
            active_epoch=rdb.active_epoch,
            duration_configuration_revision=rdb.duration_configuration_revision,
            active_duration_seconds=rdb.active_duration_seconds,
        )

    async def prepare_endpoint(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        port: int,
        label: str | None,
        operation: RuntimeWebOperationIdentity,
        endpoint_limit: int,
    ) -> RuntimeWebMutationResult:
        """Create or load one stable endpoint idempotently."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.PREPARE,
        )
        if replay is not None:
            return replay
        await self._lock_scopes(
            session,
            agent_id=agent_id,
            agent_session_id=agent_session_id,
        )
        rdb = await self._get_endpoint_by_session_port(
            session,
            agent_session_id=agent_session_id,
            port=port,
            for_update=True,
        )
        if rdb is None:
            count = await session.scalar(
                sa.select(sa.func.count(RDBRuntimeWebEndpoint.id)).where(
                    RDBRuntimeWebEndpoint.agent_session_id == agent_session_id
                )
            )
            if (count or 0) >= endpoint_limit:
                raise RuntimeWebRepositoryQuotaExceeded("session_endpoints")
            rdb = RDBRuntimeWebEndpoint(
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                port=port,
                hostname_key=uuid7().hex,
                label=label,
            )
            session.add(rdb)
            await session.flush()
        elif label is not None and rdb.label != label:
            rdb.label = label
            rdb.authority_revision += 1
            await session.flush()
            await session.refresh(rdb, attribute_names=["updated_at"])
        result = RuntimeWebMutationResult(
            endpoint=self._endpoint(rdb),
            request=await self._request_by_id(session, rdb.current_pending_request_id),
            cycle=await self._cycle_by_id(session, rdb.current_cycle_id),
        )
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.PREPARE,
            result=result,
        )
        return result

    async def request_exposure(
        self,
        session: AsyncSession,
        *,
        endpoint_id: str,
        actor_kind: RuntimeWebRequesterKind,
        requester_user_id: str | None,
        requester_agent_id: str | None,
        requester_call_id: str | None,
        label: str | None,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Create or reuse the one pending request without changing active cycle."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.REQUEST,
        )
        if replay is not None:
            return replay
        endpoint = await self._endpoint_by_id(session, endpoint_id, for_update=True)
        if endpoint is None:
            raise RuntimeWebRepositoryConflict("Endpoint not found")
        request = await self._request_by_id(
            session,
            endpoint.current_pending_request_id,
        )
        if request is None:
            rdb_request = RDBRuntimeWebRequest(
                endpoint_id=endpoint.id,
                requester_kind=actor_kind,
                operation_key=operation.operation_key,
                requester_user_id=requester_user_id,
                requester_agent_id=requester_agent_id,
                requester_execution_id=operation.execution_id,
                requester_call_id=requester_call_id,
                label_snapshot=label,
            )
            session.add(rdb_request)
            await session.flush()
            endpoint.current_pending_request_id = rdb_request.id
            endpoint.authority_revision += 1
            await session.flush()
            await session.refresh(endpoint, attribute_names=["updated_at"])
            request = self._request(rdb_request)
        result = RuntimeWebMutationResult(
            endpoint=self._endpoint(endpoint),
            request=request,
            cycle=await self._cycle_by_id(session, endpoint.current_cycle_id),
        )
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.REQUEST,
            result=result,
        )
        return result

    async def direct_create(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        agent_session_id: str,
        port: int,
        label: str | None,
        requester_user_id: str,
        requester_call_id: str | None,
        duration_seconds: int,
        duration_configuration_revision: int,
        operation: RuntimeWebOperationIdentity,
        endpoint_limit: int,
        active_session_limit: int,
        active_agent_limit: int,
    ) -> RuntimeWebMutationResult:
        """Create an explicitly confirmed request and cycle atomically."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.DIRECT_CREATE,
        )
        if replay is not None:
            return replay
        async with session.begin_nested():
            prepared = await self.prepare_endpoint(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                agent_session_id=agent_session_id,
                port=port,
                label=label,
                operation=self._suboperation(operation, "prepare"),
                endpoint_limit=endpoint_limit,
            )
            requested = await self.request_exposure(
                session,
                endpoint_id=prepared.endpoint.id,
                actor_kind=RuntimeWebRequesterKind.USER,
                requester_user_id=requester_user_id,
                requester_agent_id=None,
                requester_call_id=requester_call_id,
                label=label,
                operation=self._suboperation(operation, "request"),
            )
            if requested.request is None:
                raise RuntimeWebRepositoryConflict("Pending request missing")
            result = await self.approve_request(
                session,
                request_id=requested.request.id,
                expected_revision=requested.request.revision,
                approver_user_id=requester_user_id,
                duration_seconds=duration_seconds,
                duration_configuration_revision=duration_configuration_revision,
                operation=self._suboperation(operation, "approve"),
                active_session_limit=active_session_limit,
                active_agent_limit=active_agent_limit,
            )
            await self._record_receipt(
                session,
                operation=operation,
                kind=RuntimeWebOperationKind.DIRECT_CREATE,
                result=result,
            )
        return result

    async def approve_request(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        expected_revision: int,
        approver_user_id: str,
        duration_seconds: int,
        duration_configuration_revision: int,
        operation: RuntimeWebOperationIdentity,
        active_session_limit: int,
        active_agent_limit: int,
    ) -> RuntimeWebMutationResult:
        """Approve the exact pending request and atomically replace its cycle."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.APPROVE,
        )
        if replay is not None:
            return replay
        request = await self._request_rdb_by_id(session, request_id)
        if request is None:
            raise RuntimeWebRepositoryConflict("Request not found")
        endpoint_snapshot = await session.get(
            RDBRuntimeWebEndpoint, request.endpoint_id
        )
        if endpoint_snapshot is None:
            raise RuntimeWebRepositoryConflict("Endpoint not found")
        await self._lock_scopes(
            session,
            agent_id=endpoint_snapshot.agent_id,
            agent_session_id=endpoint_snapshot.agent_session_id,
        )
        endpoint = await self._endpoint_by_id(
            session,
            endpoint_snapshot.id,
            for_update=True,
        )
        request = await self._request_rdb_by_id(
            session,
            request_id,
            for_update=True,
        )
        if (
            endpoint is None
            or request is None
            or endpoint.current_pending_request_id != request.id
            or request.state is not RuntimeWebRequestState.PENDING
            or request.revision != expected_revision
        ):
            raise RuntimeWebRepositoryConflict("Pending request changed")
        configuration = await self.get_configuration(session)
        if (
            configuration is None
            or not configuration.enabled
            or configuration.duration_configuration_revision
            != duration_configuration_revision
            or configuration.active_duration_seconds != duration_seconds
        ):
            raise RuntimeWebRepositoryConflict("Duration configuration changed")
        now = await self._database_now(session)
        await self._expire_current_cycles(session, now=now)
        session_count = await self._active_count(
            session,
            now=now,
            agent_session_id=endpoint.agent_session_id,
            agent_id=None,
            excluding_endpoint_id=endpoint.id,
        )
        agent_count = await self._active_count(
            session,
            now=now,
            agent_session_id=None,
            agent_id=endpoint.agent_id,
            excluding_endpoint_id=endpoint.id,
        )
        if session_count >= active_session_limit:
            raise RuntimeWebRepositoryQuotaExceeded("session_active")
        if agent_count >= active_agent_limit:
            raise RuntimeWebRepositoryQuotaExceeded("agent_active")
        prior = await self._cycle_rdb_by_id(
            session,
            endpoint.current_cycle_id,
            for_update=True,
        )
        if prior is not None and prior.ended_at is None:
            prior.ended_at = now
            prior.end_reason = RuntimeWebCycleEndReason.REPLACED
        request.state = RuntimeWebRequestState.APPROVED
        request.revision += 1
        request.decided_by_user_id = approver_user_id
        request.decided_at = now
        cycle = RDBRuntimeWebCycle(
            endpoint_id=endpoint.id,
            request_id=request.id,
            approver_user_id=approver_user_id,
            duration_seconds=duration_seconds,
            duration_configuration_revision=duration_configuration_revision,
            approved_at=now,
            expires_at=now + datetime.timedelta(seconds=duration_seconds),
            close_barrier=endpoint.close_barrier,
        )
        session.add(cycle)
        await session.flush()
        endpoint.current_pending_request_id = None
        endpoint.current_cycle_id = cycle.id
        endpoint.authority_revision += 1
        await session.flush()
        await session.refresh(endpoint, attribute_names=["updated_at"])
        await session.refresh(request, attribute_names=["updated_at"])
        result = RuntimeWebMutationResult(
            endpoint=self._endpoint(endpoint),
            request=self._request(request),
            cycle=self._cycle(cycle),
        )
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.APPROVE,
            result=result,
        )
        return result

    async def decide_request(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        expected_revision: int,
        decided_by_user_id: str | None,
        state: RuntimeWebRequestState,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
    ) -> RuntimeWebMutationResult:
        """Reject or cancel the exact pending request."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=kind,
        )
        if replay is not None:
            return replay
        request = await self._request_rdb_by_id(session, request_id)
        if request is None:
            raise RuntimeWebRepositoryConflict("Request not found")
        endpoint = await self._endpoint_by_id(
            session,
            request.endpoint_id,
            for_update=True,
        )
        request = await self._request_rdb_by_id(
            session,
            request_id,
            for_update=True,
        )
        if (
            endpoint is None
            or request is None
            or endpoint.current_pending_request_id != request.id
            or request.state is not RuntimeWebRequestState.PENDING
            or request.revision != expected_revision
        ):
            raise RuntimeWebRepositoryConflict("Pending request changed")
        now = await self._database_now(session)
        request.state = state
        request.revision += 1
        request.decided_by_user_id = decided_by_user_id
        request.decided_at = now
        endpoint.current_pending_request_id = None
        endpoint.authority_revision += 1
        await session.flush()
        await session.refresh(endpoint, attribute_names=["updated_at"])
        await session.refresh(request, attribute_names=["updated_at"])
        result = RuntimeWebMutationResult(
            endpoint=self._endpoint(endpoint),
            request=self._request(request),
            cycle=await self._cycle_by_id(session, endpoint.current_cycle_id),
        )
        await self._record_receipt(
            session,
            operation=operation,
            kind=kind,
            result=result,
        )
        return result

    async def close_cycle(
        self,
        session: AsyncSession,
        *,
        cycle_id: str,
        expected_endpoint_revision: int,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Close only the exact current cycle."""
        replay = await self._mutation_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.CLOSE,
        )
        if replay is not None:
            return replay
        cycle_snapshot = await self._cycle_rdb_by_id(session, cycle_id)
        if cycle_snapshot is None:
            raise RuntimeWebRepositoryConflict("Cycle not found")
        endpoint = await self._endpoint_by_id(
            session,
            cycle_snapshot.endpoint_id,
            for_update=True,
        )
        cycle = await self._cycle_rdb_by_id(session, cycle_id, for_update=True)
        if (
            endpoint is None
            or cycle is None
            or endpoint.current_cycle_id != cycle.id
            or endpoint.authority_revision != expected_endpoint_revision
            or cycle.ended_at is not None
        ):
            raise RuntimeWebRepositoryConflict("Current cycle changed")
        now = await self._database_now(session)
        endpoint.close_barrier += 1
        endpoint.authority_revision += 1
        endpoint.current_cycle_id = None
        cycle.ended_at = now
        cycle.end_reason = RuntimeWebCycleEndReason.CLOSED
        await session.flush()
        await session.refresh(endpoint, attribute_names=["updated_at"])
        result = RuntimeWebMutationResult(
            endpoint=self._endpoint(endpoint),
            request=await self._request_by_id(
                session,
                endpoint.current_pending_request_id,
            ),
            cycle=self._cycle(cycle),
        )
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.CLOSE,
            result=result,
        )
        return result

    async def get_endpoint(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        port: int,
    ) -> RuntimeWebEndpoint | None:
        """Load one endpoint by concrete Session and port."""
        rdb = await self._get_endpoint_by_session_port(
            session,
            agent_session_id=agent_session_id,
            port=port,
            for_update=False,
        )
        return None if rdb is None else self._endpoint(rdb)

    async def list_endpoints(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        offset: int,
        limit: int,
    ) -> tuple[list[RuntimeWebEndpoint], int]:
        """List stable endpoints for one concrete Session."""
        where = RDBRuntimeWebEndpoint.agent_session_id == agent_session_id
        rows = await session.scalars(
            sa.select(RDBRuntimeWebEndpoint)
            .where(where)
            .order_by(RDBRuntimeWebEndpoint.created_at, RDBRuntimeWebEndpoint.id)
            .offset(offset)
            .limit(limit)
        )
        total = await session.scalar(
            sa.select(sa.func.count(RDBRuntimeWebEndpoint.id)).where(where)
        )
        return [self._endpoint(row) for row in rows], total or 0

    async def current_request(
        self,
        session: AsyncSession,
        endpoint: RuntimeWebEndpoint,
    ) -> RuntimeWebRequest | None:
        """Load endpoint's current pending request."""
        return await self._request_by_id(session, endpoint.current_pending_request_id)

    async def current_cycle(
        self,
        session: AsyncSession,
        endpoint: RuntimeWebEndpoint,
    ) -> RuntimeWebCycle | None:
        """Load endpoint's current cycle."""
        return await self._cycle_by_id(session, endpoint.current_cycle_id)

    async def endpoint_for_request(
        self,
        session: AsyncSession,
        request_id: str,
    ) -> RuntimeWebEndpoint | None:
        """Load endpoint containing one request."""
        request = await self._request_rdb_by_id(session, request_id)
        if request is None:
            return None
        endpoint = await session.get(RDBRuntimeWebEndpoint, request.endpoint_id)
        return None if endpoint is None else self._endpoint(endpoint)

    async def endpoint_for_cycle(
        self,
        session: AsyncSession,
        cycle_id: str,
    ) -> RuntimeWebEndpoint | None:
        """Load endpoint containing one cycle."""
        cycle = await self._cycle_rdb_by_id(session, cycle_id)
        if cycle is None:
            return None
        endpoint = await session.get(RDBRuntimeWebEndpoint, cycle.endpoint_id)
        return None if endpoint is None else self._endpoint(endpoint)

    async def _lock_scopes(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        agent_session_id: str,
    ) -> None:
        for scope_kind, subject_id in (
            (RuntimeWebQuotaScopeKind.AGENT, agent_id),
            (RuntimeWebQuotaScopeKind.SESSION, agent_session_id),
        ):
            await session.execute(
                pg_insert(RDBRuntimeWebQuotaScope)
                .values(scope_kind=scope_kind, subject_id=subject_id)
                .on_conflict_do_nothing()
            )
            await session.execute(
                sa.select(RDBRuntimeWebQuotaScope)
                .where(
                    RDBRuntimeWebQuotaScope.scope_kind == scope_kind,
                    RDBRuntimeWebQuotaScope.subject_id == subject_id,
                )
                .with_for_update()
            )

    async def _active_count(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        agent_session_id: str | None,
        agent_id: str | None,
        excluding_endpoint_id: str,
    ) -> int:
        statement = (
            sa.select(sa.func.count(sa.distinct(RDBRuntimeWebCycle.endpoint_id)))
            .join(
                RDBRuntimeWebEndpoint,
                RDBRuntimeWebEndpoint.id == RDBRuntimeWebCycle.endpoint_id,
            )
            .where(
                RDBRuntimeWebCycle.ended_at.is_(None),
                RDBRuntimeWebCycle.expires_at > now,
                RDBRuntimeWebCycle.endpoint_id != excluding_endpoint_id,
            )
        )
        if agent_session_id is not None:
            statement = statement.where(
                RDBRuntimeWebEndpoint.agent_session_id == agent_session_id
            )
        if agent_id is not None:
            statement = statement.where(RDBRuntimeWebEndpoint.agent_id == agent_id)
        return int(await session.scalar(statement) or 0)

    async def _expire_current_cycles(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
    ) -> None:
        await session.execute(
            sa.update(RDBRuntimeWebCycle)
            .where(
                RDBRuntimeWebCycle.ended_at.is_(None),
                RDBRuntimeWebCycle.expires_at <= now,
            )
            .values(ended_at=now, end_reason=RuntimeWebCycleEndReason.EXPIRED)
        )

    async def _mutation_replay(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
    ) -> RuntimeWebMutationResult | None:
        lock_material = "\0".join(
            (
                operation.actor_kind.value,
                operation.actor_id,
                operation.execution_id,
                operation.operation_key,
                kind.value,
            )
        )
        lock_key = int.from_bytes(
            hashlib.sha256(lock_material.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )
        receipt = await session.scalar(
            sa.select(RDBRuntimeWebOperationReceipt).where(
                RDBRuntimeWebOperationReceipt.actor_kind == operation.actor_kind,
                RDBRuntimeWebOperationReceipt.actor_id == operation.actor_id,
                RDBRuntimeWebOperationReceipt.execution_id == operation.execution_id,
                RDBRuntimeWebOperationReceipt.operation_key == operation.operation_key,
                RDBRuntimeWebOperationReceipt.operation_kind == kind,
            )
        )
        if receipt is None:
            return None
        endpoint = await self._endpoint_by_id(
            session,
            receipt.endpoint_id,
            for_update=False,
        )
        if endpoint is None:
            raise RuntimeError("Runtime Web receipt endpoint is missing")
        return RuntimeWebMutationResult(
            endpoint=self._endpoint(endpoint),
            request=await self._request_by_id(session, receipt.request_id),
            cycle=await self._cycle_by_id(session, receipt.cycle_id),
        )

    async def _record_receipt(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
        result: RuntimeWebMutationResult,
    ) -> None:
        session.add(
            RDBRuntimeWebOperationReceipt(
                actor_kind=operation.actor_kind,
                actor_id=operation.actor_id,
                execution_id=operation.execution_id,
                operation_key=operation.operation_key,
                operation_kind=kind,
                result={"endpoint_id": result.endpoint.id},
                endpoint_id=result.endpoint.id,
                request_id=None if result.request is None else result.request.id,
                cycle_id=None if result.cycle is None else result.cycle.id,
            )
        )
        await session.flush()

    async def _get_endpoint_by_session_port(
        self,
        session: AsyncSession,
        *,
        agent_session_id: str,
        port: int,
        for_update: bool,
    ) -> RDBRuntimeWebEndpoint | None:
        statement = sa.select(RDBRuntimeWebEndpoint).where(
            RDBRuntimeWebEndpoint.agent_session_id == agent_session_id,
            RDBRuntimeWebEndpoint.port == port,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _endpoint_by_id(
        self,
        session: AsyncSession,
        endpoint_id: str | None,
        *,
        for_update: bool,
    ) -> RDBRuntimeWebEndpoint | None:
        if endpoint_id is None:
            return None
        statement = sa.select(RDBRuntimeWebEndpoint).where(
            RDBRuntimeWebEndpoint.id == endpoint_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _request_rdb_by_id(
        self,
        session: AsyncSession,
        request_id: str | None,
        *,
        for_update: bool = False,
    ) -> RDBRuntimeWebRequest | None:
        if request_id is None:
            return None
        statement = sa.select(RDBRuntimeWebRequest).where(
            RDBRuntimeWebRequest.id == request_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _cycle_rdb_by_id(
        self,
        session: AsyncSession,
        cycle_id: str | None,
        *,
        for_update: bool = False,
    ) -> RDBRuntimeWebCycle | None:
        if cycle_id is None:
            return None
        statement = sa.select(RDBRuntimeWebCycle).where(
            RDBRuntimeWebCycle.id == cycle_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _request_by_id(
        self,
        session: AsyncSession,
        request_id: str | None,
    ) -> RuntimeWebRequest | None:
        rdb = await self._request_rdb_by_id(session, request_id)
        return None if rdb is None else self._request(rdb)

    async def _cycle_by_id(
        self,
        session: AsyncSession,
        cycle_id: str | None,
    ) -> RuntimeWebCycle | None:
        rdb = await self._cycle_rdb_by_id(session, cycle_id)
        return None if rdb is None else self._cycle(rdb)

    async def _database_now(self, session: AsyncSession) -> datetime.datetime:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return now

    def _endpoint(self, rdb: RDBRuntimeWebEndpoint) -> RuntimeWebEndpoint:
        return RuntimeWebEndpoint.model_validate(rdb, from_attributes=True)

    def _request(self, rdb: RDBRuntimeWebRequest) -> RuntimeWebRequest:
        return RuntimeWebRequest.model_validate(rdb, from_attributes=True)

    def _cycle(self, rdb: RDBRuntimeWebCycle) -> RuntimeWebCycle:
        return RuntimeWebCycle.model_validate(rdb, from_attributes=True)

    @staticmethod
    def _suboperation(
        operation: RuntimeWebOperationIdentity,
        suffix: str,
    ) -> RuntimeWebOperationIdentity:
        return operation.model_copy(
            update={
                "operation_key": derived_operation_key(
                    operation.operation_key,
                    suffix,
                )
            }
        )
