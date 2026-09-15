"""Repository-owned Runtime Web service authority operations."""

import base64
import datetime
import hashlib
import json
import secrets
from collections.abc import Callable
from typing import NamedTuple

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.runtime_web import (
    RDBRuntimeWebAuthConfiguration,
    RDBRuntimeWebOperationReceipt,
    RDBRuntimeWebQuotaScope,
    RDBRuntimeWebService,
    RuntimeWebOperationKind,
)
from azents.repos.runtime_web.data import (
    RuntimeWebConfiguration,
    RuntimeWebMutationResult,
    RuntimeWebOperationIdentity,
    RuntimeWebServiceRecord,
)

_HOSTNAME_GENERATION_ATTEMPTS = 8
_SUPPORTED_DURATIONS = frozenset({3_600, 21_600, 86_400})


class RuntimeWebServicePage(NamedTuple):
    """Field-named result for ``list_services``."""

    items: list[RuntimeWebServiceRecord]
    total: int


class RuntimeWebRepositoryConflict(ValueError):
    """The expected Runtime Web authority changed."""


class RuntimeWebRepositoryQuotaExceeded(ValueError):
    """A logical Runtime Web quota is exhausted."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


class RuntimeWebRepository:
    """Durable Agent-scoped Runtime Web authority repository."""

    def __init__(
        self,
        *,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self.random_bytes = random_bytes

    async def get_configuration(
        self,
        session: AsyncSession,
    ) -> RuntimeWebConfiguration | None:
        """Load current durable authentication configuration."""
        rdb = await session.get(RDBRuntimeWebAuthConfiguration, 1)
        if rdb is None:
            return None
        return RuntimeWebConfiguration(
            enabled=rdb.enabled,
            mode=rdb.mode,
            fingerprint=rdb.fingerprint,
        )

    async def create_service(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        selected_duration_seconds: int,
        turn_on: bool,
        operation: RuntimeWebOperationIdentity,
        service_limit: int,
        active_agent_limit: int,
    ) -> RuntimeWebMutationResult:
        """Create one user-managed service and optionally turn it On."""
        payload = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "port": port,
            "label": label,
            "selected_duration_seconds": selected_duration_seconds,
            "turn_on": turn_on,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.CREATE,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        self._validate_duration(selected_duration_seconds)
        await self._lock_agent_scope(session, agent_id=agent_id)
        existing = await self._service_by_agent_port(
            session,
            agent_id=agent_id,
            port=port,
            for_update=True,
        )
        if existing is not None:
            raise RuntimeWebRepositoryConflict("Service port already exists")
        count = await session.scalar(
            sa.select(sa.func.count(RDBRuntimeWebService.id)).where(
                RDBRuntimeWebService.agent_id == agent_id
            )
        )
        if int(count or 0) >= service_limit:
            raise RuntimeWebRepositoryQuotaExceeded("agent_services")
        now = await self._database_now(session)
        if turn_on:
            await self._require_active_capacity(
                session,
                agent_id=agent_id,
                excluding_service_id=None,
                active_agent_limit=active_agent_limit,
                now=now,
            )
        rdb = await self._insert_with_random_hostname(
            session,
            workspace_id=workspace_id,
            agent_id=agent_id,
            port=port,
            label=label,
            selected_duration_seconds=selected_duration_seconds,
            exposure_deadline_at=(
                now + datetime.timedelta(seconds=selected_duration_seconds)
                if turn_on
                else None
            ),
        )
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.CREATE,
            payload=payload,
            result=result,
        )
        return result

    async def request_service(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        operation: RuntimeWebOperationIdentity,
        service_limit: int,
    ) -> RuntimeWebMutationResult:
        """Create one missing Off service or return the existing service unchanged."""
        payload = {
            "workspace_id": workspace_id,
            "agent_id": agent_id,
            "port": port,
            "label": label,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.REQUEST,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        await self._lock_agent_scope(session, agent_id=agent_id)
        rdb = await self._service_by_agent_port(
            session,
            agent_id=agent_id,
            port=port,
            for_update=True,
        )
        if rdb is None:
            count = await session.scalar(
                sa.select(sa.func.count(RDBRuntimeWebService.id)).where(
                    RDBRuntimeWebService.agent_id == agent_id
                )
            )
            if int(count or 0) >= service_limit:
                raise RuntimeWebRepositoryQuotaExceeded("agent_services")
            rdb = await self._insert_with_random_hostname(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
                port=port,
                label=label,
                selected_duration_seconds=3_600,
                exposure_deadline_at=None,
            )
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.REQUEST,
            payload=payload,
            result=result,
        )
        return result

    async def update_service(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        expected_revision: int,
        label_present: bool,
        label: str | None,
        selected_duration_seconds: int | None,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Update service metadata without changing its current deadline."""
        payload = {
            "service_id": service_id,
            "expected_revision": expected_revision,
            "label_present": label_present,
            "label": label,
            "selected_duration_seconds": selected_duration_seconds,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.UPDATE,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        if selected_duration_seconds is not None:
            self._validate_duration(selected_duration_seconds)
        rdb = await self._service_by_id(session, service_id, for_update=True)
        self._require_revision(rdb, expected_revision)
        assert rdb is not None
        changed = False
        if label_present and rdb.label != label:
            rdb.label = label
            changed = True
        if (
            selected_duration_seconds is not None
            and rdb.selected_duration_seconds != selected_duration_seconds
        ):
            rdb.selected_duration_seconds = selected_duration_seconds
            changed = True
        if changed:
            rdb.revision += 1
            await self._flush_updated(session, rdb)
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.UPDATE,
            payload=payload,
            result=result,
        )
        return result

    async def turn_on(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        expected_revision: int,
        selected_duration_seconds: int | None,
        operation: RuntimeWebOperationIdentity,
        active_agent_limit: int,
    ) -> RuntimeWebMutationResult:
        """Turn an Off service On using its selected duration."""
        payload = {
            "service_id": service_id,
            "expected_revision": expected_revision,
            "selected_duration_seconds": selected_duration_seconds,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.TURN_ON,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        if selected_duration_seconds is not None:
            self._validate_duration(selected_duration_seconds)
        snapshot = await self._service_by_id(session, service_id, for_update=False)
        if snapshot is None:
            raise RuntimeWebRepositoryConflict("Service not found")
        await self._lock_agent_scope(session, agent_id=snapshot.agent_id)
        rdb = await self._service_by_id(session, service_id, for_update=True)
        self._require_revision(rdb, expected_revision)
        assert rdb is not None
        now = await self._database_now(session)
        if rdb.exposure_deadline_at is not None and rdb.exposure_deadline_at > now:
            raise RuntimeWebRepositoryConflict("Service is already On")
        await self._require_active_capacity(
            session,
            agent_id=rdb.agent_id,
            excluding_service_id=rdb.id,
            active_agent_limit=active_agent_limit,
            now=now,
        )
        if selected_duration_seconds is not None:
            rdb.selected_duration_seconds = selected_duration_seconds
        rdb.exposure_deadline_at = now + datetime.timedelta(
            seconds=rdb.selected_duration_seconds
        )
        rdb.revision += 1
        await self._flush_updated(session, rdb)
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.TURN_ON,
            payload=payload,
            result=result,
        )
        return result

    async def turn_off(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        expected_revision: int,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Turn one exact service Off with optimistic revision fencing."""
        return await self._turn_off(
            session,
            service_id=service_id,
            expected_revision=expected_revision,
            operation=operation,
            kind=RuntimeWebOperationKind.TURN_OFF,
        )

    async def close_service(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Idempotently turn one exact service Off for an Agent caller."""
        return await self._turn_off(
            session,
            service_id=service_id,
            expected_revision=None,
            operation=operation,
            kind=RuntimeWebOperationKind.CLOSE,
        )

    async def reset_expiration(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        expected_revision: int,
        operation: RuntimeWebOperationIdentity,
    ) -> RuntimeWebMutationResult:
        """Restart an On service window using the selected duration."""
        payload = {
            "service_id": service_id,
            "expected_revision": expected_revision,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.RESET,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        rdb = await self._service_by_id(session, service_id, for_update=True)
        self._require_revision(rdb, expected_revision)
        assert rdb is not None
        now = await self._database_now(session)
        if rdb.exposure_deadline_at is None or rdb.exposure_deadline_at <= now:
            raise RuntimeWebRepositoryConflict("Service is Off")
        rdb.exposure_deadline_at = now + datetime.timedelta(
            seconds=rdb.selected_duration_seconds
        )
        rdb.revision += 1
        await self._flush_updated(session, rdb)
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.RESET,
            payload=payload,
            result=result,
        )
        return result

    async def delete_service(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        service_id: str,
        expected_revision: int,
        operation: RuntimeWebOperationIdentity,
    ) -> bool:
        """Delete an exact service; a missing service is an authorized success."""
        payload = {
            "agent_id": agent_id,
            "service_id": service_id,
            "expected_revision": expected_revision,
        }
        replay = await self._receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.DELETE,
            payload=payload,
        )
        if replay is not None:
            return bool(replay.result.get("deleted", False))
        rdb = await self._service_by_id(session, service_id, for_update=True)
        if rdb is not None and (
            rdb.agent_id != agent_id or rdb.revision != expected_revision
        ):
            raise RuntimeWebRepositoryConflict("Service changed")
        if rdb is not None:
            await session.delete(rdb)
            await session.flush()
        await self._record_raw_receipt(
            session,
            operation=operation,
            kind=RuntimeWebOperationKind.DELETE,
            payload=payload,
            service_id=None,
            result={"service_id": service_id, "deleted": True},
        )
        return True

    async def get_service(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        port: int,
    ) -> RuntimeWebServiceRecord | None:
        """Load one service by Agent and port."""
        rdb = await self._service_by_agent_port(
            session,
            agent_id=agent_id,
            port=port,
            for_update=False,
        )
        return None if rdb is None else self._service(rdb)

    async def get_service_by_id(
        self,
        session: AsyncSession,
        service_id: str,
    ) -> RuntimeWebServiceRecord | None:
        """Load one service by opaque row identity."""
        rdb = await self._service_by_id(session, service_id, for_update=False)
        return None if rdb is None else self._service(rdb)

    async def get_service_by_hostname(
        self,
        session: AsyncSession,
        *,
        hostname_key: str,
    ) -> RuntimeWebServiceRecord | None:
        """Load one service by exact public hostname key."""
        rdb = await session.scalar(
            sa.select(RDBRuntimeWebService).where(
                RDBRuntimeWebService.hostname_key == hostname_key
            )
        )
        return None if rdb is None else self._service(rdb)

    async def list_services(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        offset: int,
        limit: int,
    ) -> RuntimeWebServicePage:
        """List stable services for one Agent."""
        where = RDBRuntimeWebService.agent_id == agent_id
        rows = await session.scalars(
            sa.select(RDBRuntimeWebService)
            .where(where)
            .order_by(RDBRuntimeWebService.created_at, RDBRuntimeWebService.id)
            .offset(offset)
            .limit(limit)
        )
        total = await session.scalar(
            sa.select(sa.func.count(RDBRuntimeWebService.id)).where(where)
        )
        return RuntimeWebServicePage(
            items=[self._service(row) for row in rows],
            total=int(total or 0),
        )

    async def delete_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> int:
        """Delete every service owned by one Agent."""
        result = await session.execute(
            sa.delete(RDBRuntimeWebService)
            .where(RDBRuntimeWebService.agent_id == agent_id)
            .returning(RDBRuntimeWebService.id)
        )
        return len(result.scalars().all())

    async def count_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> int:
        """Count services remaining for one Agent."""
        return int(
            await session.scalar(
                sa.select(sa.func.count(RDBRuntimeWebService.id)).where(
                    RDBRuntimeWebService.agent_id == agent_id
                )
            )
            or 0
        )

    async def _turn_off(
        self,
        session: AsyncSession,
        *,
        service_id: str,
        expected_revision: int | None,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
    ) -> RuntimeWebMutationResult:
        payload = {
            "service_id": service_id,
            "expected_revision": expected_revision,
        }
        replay = await self._service_replay(
            session,
            operation=operation,
            kind=kind,
            payload=payload,
        )
        if replay is not None:
            return RuntimeWebMutationResult(service=replay)
        rdb = await self._service_by_id(session, service_id, for_update=True)
        if rdb is None or (
            expected_revision is not None and rdb.revision != expected_revision
        ):
            raise RuntimeWebRepositoryConflict("Service changed")
        now = await self._database_now(session)
        if rdb.exposure_deadline_at is not None:
            if rdb.exposure_deadline_at > now:
                rdb.revision += 1
            rdb.exposure_deadline_at = None
            await self._flush_updated(session, rdb)
        result = RuntimeWebMutationResult(service=self._service(rdb))
        await self._record_receipt(
            session,
            operation=operation,
            kind=kind,
            payload=payload,
            result=result,
        )
        return result

    async def _insert_with_random_hostname(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        agent_id: str,
        port: int,
        label: str | None,
        selected_duration_seconds: int,
        exposure_deadline_at: datetime.datetime | None,
    ) -> RDBRuntimeWebService:
        for _ in range(_HOSTNAME_GENERATION_ATTEMPTS):
            candidate = self._hostname_key()
            try:
                async with session.begin_nested():
                    rdb = RDBRuntimeWebService(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        port=port,
                        hostname_key=candidate,
                        label=label,
                        selected_duration_seconds=selected_duration_seconds,
                        exposure_deadline_at=exposure_deadline_at,
                    )
                    session.add(rdb)
                    await session.flush()
                return rdb
            except IntegrityError as error:
                if "uq_runtime_web_services_hostname_key" not in str(error):
                    raise
        raise RuntimeWebRepositoryConflict("Hostname generation exhausted")

    def _hostname_key(self) -> str:
        encoded = base64.b32encode(self.random_bytes(8)).decode().lower().rstrip("=")
        return encoded[:12]

    async def _lock_agent_scope(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> None:
        await session.execute(
            pg_insert(RDBRuntimeWebQuotaScope)
            .values(agent_id=agent_id)
            .on_conflict_do_nothing()
        )
        await session.execute(
            sa.select(RDBRuntimeWebQuotaScope)
            .where(RDBRuntimeWebQuotaScope.agent_id == agent_id)
            .with_for_update()
        )

    async def _require_active_capacity(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        excluding_service_id: str | None,
        active_agent_limit: int,
        now: datetime.datetime,
    ) -> None:
        statement = sa.select(sa.func.count(RDBRuntimeWebService.id)).where(
            RDBRuntimeWebService.agent_id == agent_id,
            RDBRuntimeWebService.exposure_deadline_at > now,
        )
        if excluding_service_id is not None:
            statement = statement.where(RDBRuntimeWebService.id != excluding_service_id)
        if int(await session.scalar(statement) or 0) >= active_agent_limit:
            raise RuntimeWebRepositoryQuotaExceeded("agent_active")

    async def _service_replay(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
        payload: object,
    ) -> RuntimeWebServiceRecord | None:
        receipt = await self._receipt(
            session,
            operation=operation,
            kind=kind,
            payload=payload,
        )
        if receipt is None:
            return None
        service_id = receipt.service_id
        if service_id is None:
            raise RuntimeWebRepositoryConflict("Operation target is no longer present")
        service = await self._service_by_id(session, service_id, for_update=False)
        if service is None:
            raise RuntimeWebRepositoryConflict("Operation target is no longer present")
        return self._service(service)

    async def _receipt(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
        payload: object,
    ) -> RDBRuntimeWebOperationReceipt | None:
        await self._lock_operation(session, operation=operation, kind=kind)
        receipt = await session.scalar(
            sa.select(RDBRuntimeWebOperationReceipt).where(
                RDBRuntimeWebOperationReceipt.actor_kind == operation.actor_kind,
                RDBRuntimeWebOperationReceipt.actor_id == operation.actor_id,
                RDBRuntimeWebOperationReceipt.execution_id == operation.execution_id,
                RDBRuntimeWebOperationReceipt.operation_key == operation.operation_key,
                RDBRuntimeWebOperationReceipt.operation_kind == kind,
            )
        )
        if receipt is not None and receipt.input_fingerprint != self._fingerprint(
            payload
        ):
            raise RuntimeWebRepositoryConflict("Idempotency input changed")
        return receipt

    async def _record_receipt(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
        payload: object,
        result: RuntimeWebMutationResult,
    ) -> None:
        await self._record_raw_receipt(
            session,
            operation=operation,
            kind=kind,
            payload=payload,
            service_id=result.service.id,
            result={"service_id": result.service.id},
        )

    async def _record_raw_receipt(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
        payload: object,
        service_id: str | None,
        result: dict[str, object],
    ) -> None:
        session.add(
            RDBRuntimeWebOperationReceipt(
                actor_kind=operation.actor_kind,
                actor_id=operation.actor_id,
                execution_id=operation.execution_id,
                operation_key=operation.operation_key,
                operation_kind=kind,
                input_fingerprint=self._fingerprint(payload),
                result=result,
                service_id=service_id,
            )
        )
        await session.flush()

    async def _lock_operation(
        self,
        session: AsyncSession,
        *,
        operation: RuntimeWebOperationIdentity,
        kind: RuntimeWebOperationKind,
    ) -> None:
        material = "\0".join(
            (
                operation.actor_kind.value,
                operation.actor_id,
                operation.execution_id,
                operation.operation_key,
                kind.value,
            )
        )
        lock_key = int.from_bytes(
            hashlib.sha256(material.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )
        await session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    async def _service_by_agent_port(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        port: int,
        for_update: bool,
    ) -> RDBRuntimeWebService | None:
        statement = sa.select(RDBRuntimeWebService).where(
            RDBRuntimeWebService.agent_id == agent_id,
            RDBRuntimeWebService.port == port,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _service_by_id(
        self,
        session: AsyncSession,
        service_id: str,
        *,
        for_update: bool,
    ) -> RDBRuntimeWebService | None:
        statement = sa.select(RDBRuntimeWebService).where(
            RDBRuntimeWebService.id == service_id
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def _database_now(self, session: AsyncSession) -> datetime.datetime:
        now = await session.scalar(sa.select(sa.func.now()))
        if not isinstance(now, datetime.datetime):
            raise RuntimeError("Database did not return current timestamp")
        return now

    async def _flush_updated(
        self,
        session: AsyncSession,
        rdb: RDBRuntimeWebService,
    ) -> None:
        await session.flush()
        await session.refresh(rdb, attribute_names=["updated_at"])

    @staticmethod
    def _require_revision(
        rdb: RDBRuntimeWebService | None,
        expected_revision: int,
    ) -> None:
        if rdb is None or rdb.revision != expected_revision:
            raise RuntimeWebRepositoryConflict("Service revision changed")

    @staticmethod
    def _validate_duration(duration_seconds: int) -> None:
        if duration_seconds not in _SUPPORTED_DURATIONS:
            raise RuntimeWebRepositoryConflict("Unsupported service duration")

    @staticmethod
    def _fingerprint(payload: object) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _service(rdb: RDBRuntimeWebService) -> RuntimeWebServiceRecord:
        return RuntimeWebServiceRecord.model_validate(rdb, from_attributes=True)


def get_runtime_web_repository() -> RuntimeWebRepository:
    """Create the Runtime Web repository dependency."""
    return RuntimeWebRepository()
