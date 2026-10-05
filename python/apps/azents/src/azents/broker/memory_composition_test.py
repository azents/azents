"""Real application/Worker composition without any Redis construction."""

import asyncio
import datetime
from typing import Annotated, Never

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import Depends

from azents.app import create_admin_api_app, create_public_api_app
from azents.broker.broadcast import InMemoryWebSocketBroadcast
from azents.broker.deps import get_broker
from azents.broker.memory import InMemoryBroker
from azents.broker.types import (
    BrokerMessage,
    SessionBroker,
    SessionStopSignal,
    SessionWakeUp,
)
from azents.broker.websocket_deps import get_websocket_broadcast
from azents.core.config import Config, Settings
from azents.core.deps import get_appctx
from azents.process_lifecycle import run_co_located_container, run_with_container
from azents.repos.worker_session_data import StuckWorkerSession
from azents.repos.worker_session_recovery import (
    WorkerSessionRecoveryOperationRepository,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.deps import (
    get_runtime_coordination_store,
    get_runtime_terminal_coordination_store,
)
from azents.runtime.terminal_coordination.memory import (
    InMemoryRuntimeTerminalCoordinationStore,
)
from azents.scheduler.service import SchedulerService
from azents.services.chat.live_events import (
    InMemoryLiveEventStore,
    get_live_event_store,
)
from azents.services.external_channel.conversation_lock import (
    InMemoryExternalChannelConversationLock,
)
from azents.services.external_channel.deps import get_external_channel_conversation_lock
from azents.services.runtime_provider_control.deps import (
    get_runtime_provider_enrollment_rate_limiter,
)
from azents.services.runtime_provider_control.rate_limit import (
    InMemoryRuntimeProviderEnrollmentRateLimiter,
)
from azents.worker.deps import get_broadcast, get_worker_broker, get_worker_redis
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.recovery import StuckSessionRecovery
from azents.worker.session.runner import SessionRunner
from azents.worker.session.runner_factory import SessionRunnerFactory
from azents.worker.worker import AgentWorker


def _config() -> Config:
    return Config.from_settings(
        Settings(
            _env_file=None,
            rdb_host="unused",
            rdb_user="unused",
            rdb_db_name="unused",
            auth_jwt_secret_key="synthetic-jwt",
            credential_encryption_key=Fernet.generate_key().decode(),
            session_broker_backend="memory",
            runtime_transfer_coordinator_endpoint="127.0.0.1:1",
            runtime_transfer_coordinator_allow_insecure=True,
            workspace_s3_bucket="test-bucket",
            workspace_s3_access_key_id="synthetic",
            workspace_s3_secret_access_key="synthetic",
        )
    )


@pytest.fixture
def forbid_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(url: str) -> Never:
        raise AssertionError(f"Memory mode constructed Redis: {url}")

    for module in (
        "azents.broker.deps",
        "azents.broker.websocket_deps",
        "azents.worker.deps",
        "azents.runtime.deps",
        "azents.services.chat.live_events",
        "azents.services.external_channel.deps",
        "azents.services.runtime_provider_control.deps",
    ):
        monkeypatch.setattr(module + ".create_redis_client", reject)


@pytest.mark.asyncio
async def test_api_worker_and_ephemeral_services_share_memory_owners(
    forbid_redis: None,
) -> None:
    async with run_co_located_container(_config()) as container:
        api = await container.solve(get_broker)
        worker = await container.solve(get_worker_broker)
        assert isinstance(api, InMemoryBroker) and isinstance(worker, InMemoryBroker)
        assert api is await container.solve(get_broker)
        assert worker is await container.solve(get_worker_broker)
        assert api.state is worker.state
        await api.send_message(SessionWakeUp("s"))
        assert await asyncio.wait_for(worker.receive_messages(), 1) == [
            SessionWakeUp("s")
        ]
        broadcast = await container.solve(get_websocket_broadcast)
        assert isinstance(broadcast, InMemoryWebSocketBroadcast)
        assert await container.solve(get_broadcast) is broadcast
        async with broadcast.subscribe("s") as events:
            await broadcast.publish("s", {"type": "memory-delivery"})
            assert await asyncio.wait_for(anext(events), 1) == {
                "type": "memory-delivery"
            }
        assert isinstance(
            await container.solve(get_live_event_store), InMemoryLiveEventStore
        )
        assert isinstance(
            await container.solve(get_runtime_coordination_store),
            InMemoryRuntimeCoordinationStore,
        )
        assert isinstance(
            await container.solve(get_runtime_terminal_coordination_store),
            InMemoryRuntimeTerminalCoordinationStore,
        )
        assert isinstance(
            await container.solve(get_external_channel_conversation_lock),
            InMemoryExternalChannelConversationLock,
        )
        assert isinstance(
            await container.solve(get_runtime_provider_enrollment_rate_limiter),
            InMemoryRuntimeProviderEnrollmentRateLimiter,
        )
        assert await container.solve(get_worker_redis) is None
    assert api.state.closed


@pytest.mark.asyncio
async def test_complete_worker_scheduler_and_api_roots_compose_without_redis(
    forbid_redis: None,
) -> None:
    """Resolve production services without replacing their dependency graphs."""
    config = _config()
    async with run_co_located_container(config) as container:
        worker = await container.solve(AgentWorker)
        scheduler = await container.solve(SchedulerService)
        context = await container.solve(get_appctx)
        public = create_public_api_app(config, appctx=context, container=container)
        admin = create_admin_api_app(config, appctx=context, container=container)
        # Public lifespan has no database bootstrap. Admin bootstrap is covered
        # by its PostgreSQL-backed tests; both API roots retain this container.
        async with public.router.lifespan_context(public):
            assert await container.solve(AgentWorker) is worker
            assert await container.solve(SchedulerService) is scheduler
            assert public.state.di_container is admin.state.di_container is container


class _RecordingRunner(SessionRunner):
    def __init__(self, output: asyncio.Queue[BrokerMessage]) -> None:
        self.output = output
        self.pending: asyncio.Queue[BrokerMessage | None] = asyncio.Queue()

    def enqueue(self, message: BrokerMessage) -> None:
        self.pending.put_nowait(message)

    def request_shutdown(self) -> None:
        self.pending.put_nowait(None)

    def notify_mailbox_activity(self) -> None:
        pass

    async def run(self) -> None:
        while (message := await self.pending.get()) is not None:
            self.output.put_nowait(message)


class _RecordingFactory(SessionRunnerFactory):
    def __init__(self, output: asyncio.Queue[BrokerMessage]) -> None:
        self.output = output

    def create(self, *, shutdown_event: asyncio.Event) -> SessionRunner:
        return _RecordingRunner(self.output)


class _IdleRecovery(StuckSessionRecovery):
    def __init__(self) -> None:
        pass

    def start(self, shutdown_event: asyncio.Event) -> asyncio.Task[None]:
        async def idle() -> None:
            await shutdown_event.wait()

        return asyncio.create_task(idle())


@pytest.mark.asyncio
async def test_actual_api_producer_reaches_agent_worker_dispatch_without_redis(
    forbid_redis: None,
) -> None:
    config = _config()
    shutdown = asyncio.Event()
    output: asyncio.Queue[BrokerMessage] = asyncio.Queue()
    async with run_co_located_container(config) as container:

        def factory() -> SessionRunnerFactory:
            return _RecordingFactory(output)

        def recovery() -> StuckSessionRecovery:
            return _IdleRecovery()

        container.dependency_overrides.update(
            {
                SessionRunnerFactory: factory,
                StuckSessionRecovery: recovery,
            }
        )
        # Use the exact shared binding used by the supported all-in-one root.
        context = await container.solve(get_appctx)
        public = create_public_api_app(config, appctx=context, container=container)
        admin = create_admin_api_app(config, appctx=context, container=container)
        assert public.state.appctx_binding is not None
        assert admin.state.di_container is container

        @public.post("/memory-probe/{session_id}")
        async def send(
            session_id: str,
            broker: Annotated[SessionBroker, Depends(get_broker)],
        ) -> dict[str, bool]:
            await broker.send_message(SessionWakeUp(session_id))
            await broker.send_message(SessionStopSignal(session_id))
            return {"accepted": True}

        worker = await container.solve(AgentWorker)
        task = asyncio.create_task(worker.run(shutdown_event=shutdown))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=public), base_url="http://memory"
            ) as client:
                response = await client.post("/memory-probe/s")
                assert response.status_code == 200
            assert await asyncio.wait_for(output.get(), 1) == SessionWakeUp("s")
            assert await asyncio.wait_for(output.get(), 1) == SessionStopSignal("s")
        finally:
            shutdown.set()
            await asyncio.wait_for(task, 1)


class _DurableRecovery(WorkerSessionRecoveryOperationRepository):
    def __init__(self) -> None:
        pass

    async def find_stuck_running(
        self, *, stale_threshold: datetime.timedelta, limit: int
    ) -> list[StuckWorkerSession]:
        return [StuckWorkerSession(id="retained", agent_id="agent")]


class _DurableLifecycle(SessionLifecycleService):
    def __init__(self) -> None:
        self.marked: list[str] = []

    async def mark_session_running(self, session_id: str) -> None:
        self.marked.append(session_id)


@pytest.mark.asyncio
async def test_empty_memory_after_restart_accepts_existing_durable_recovery(
    forbid_redis: None,
) -> None:
    # The existing recovery repository boundary supplies retained durable work.
    async with run_co_located_container(_config()) as original:
        broker = await original.solve(get_broker)
        await broker.send_message(SessionWakeUp("discarded-ephemeral"))
    lifecycle = _DurableLifecycle()
    async with run_co_located_container(_config()) as restarted:
        worker = await restarted.solve(get_worker_broker)
        recovery = StuckSessionRecovery(
            broker=worker,
            repository=_DurableRecovery(),
            session_lifecycle=lifecycle,
        )
        await recovery.recover_once()
        assert lifecycle.marked == ["retained"]
        assert await asyncio.wait_for(worker.receive_messages(), 1) == [
            SessionWakeUp("retained")
        ]


@pytest.mark.asyncio
async def test_independent_roots_reject_memory_before_serving() -> None:
    config = _config()
    with pytest.raises(RuntimeError, match="co-located"):
        async with run_with_container(config):
            pytest.fail("Independent Worker root entered memory mode")
    with pytest.raises(ValueError, match="co-located"):
        create_public_api_app(config)
    with pytest.raises(ValueError, match="co-located"):
        create_admin_api_app(config)


def test_memory_backend_is_explicit_and_redis_remains_default() -> None:
    assert Settings.model_fields["session_broker_backend"].default == "redis"
    assert Config.model_fields["session_broker_backend"].default == "redis"
    assert _config().session_broker_backend == "memory"
