"""Worker health check HTTP server.

Lightweight aiohttp server for Kubernetes liveness/readiness probe.
Runs as separate asyncio task inside AgentWorker process.
"""

import asyncio
import contextlib
import dataclasses
import inspect
import logging

from aiohttp import web
from redis.asyncio import Redis

from azents.runtime.observability import (
    OBSERVATION_LATENCY_BUCKET_SECONDS,
    WAIT_DURATION_BUCKET_SECONDS,
    RuntimeReplyDeliveryMetrics,
)

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8012
_EVENT_LOOP_SAMPLE_INTERVAL_SECONDS = 1.0
_METRIC_LOG_INTERVAL_SAMPLES = 60


class HealthServer:
    """Lightweight health check server running inside Worker process.

    - ``/healthz`` — liveness probe (event loop response availability)
    - ``/readyz`` — readiness probe (Redis connection + shutdown status check)
    """

    def __init__(
        self,
        redis: Redis,
        *,
        metrics: RuntimeReplyDeliveryMetrics,
        port: int = _DEFAULT_PORT,
    ) -> None:
        self._redis = redis
        self._metrics = metrics
        self._port = port
        self._shutting_down = False
        self._runner: web.AppRunner | None = None
        self._event_loop_sampler: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start health check HTTP server."""
        app = web.Application()
        app.router.add_get("/healthz", self._liveness)
        app.router.add_get("/readyz", self._readiness)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)  # noqa: S104
        await site.start()
        self._event_loop_sampler = asyncio.create_task(
            self._observe_event_loop(),
            name="worker-event-loop-observability",
        )
        logger.info("Health server started", extra={"port": self._port})

    async def stop(self) -> None:
        """Stop health check HTTP server."""
        if self._event_loop_sampler is not None:
            self._event_loop_sampler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._event_loop_sampler
            self._event_loop_sampler = None
        if self._runner is not None:
            await self._runner.cleanup()

    def mark_shutting_down(self) -> None:
        """Mark graceful shutdown entry.

        After this, readiness probe returns 503.
        """
        self._shutting_down = True
        logger.info("Readiness probe now returns 503")

    async def _liveness(self, _: web.Request) -> web.Response:
        """Liveness probe — 200 when event loop is alive."""
        return web.json_response({"status": "ok"})

    async def _readiness(self, _: web.Request) -> web.Response:
        """Readiness probe — 200 when Redis connectable and not shutdown."""
        if self._shutting_down:
            return web.json_response(
                {"status": "not_ready", "reason": "shutting down"},
                status=503,
            )
        try:
            ping = (
                self._redis.ping()
            )  # redis.asyncio Redis type declaration is incomplete
            if inspect.isawaitable(ping):
                await ping
        except Exception:
            logger.warning("Readiness check failed: redis unavailable", exc_info=True)
            return web.json_response(
                {"status": "not_ready", "reason": "redis unavailable"},
                status=503,
            )
        return web.json_response({"status": "ok"})

    async def _observe_event_loop(self) -> None:
        """Sample timer drift and periodically log bounded Runtime observations."""
        loop = asyncio.get_running_loop()
        samples_since_log = 0
        while True:
            scheduled_at = loop.time() + _EVENT_LOOP_SAMPLE_INTERVAL_SECONDS
            await asyncio.sleep(_EVENT_LOOP_SAMPLE_INTERVAL_SECONDS)
            self._metrics.record_event_loop_lag(loop.time() - scheduled_at)
            samples_since_log += 1
            if samples_since_log < _METRIC_LOG_INTERVAL_SAMPLES:
                continue
            samples_since_log = 0
            snapshot = self._metrics.snapshot()
            logger.info(
                "Runtime reply delivery metrics",
                extra={
                    **dataclasses.asdict(snapshot),
                    "wait_duration_bucket_seconds": WAIT_DURATION_BUCKET_SECONDS,
                    "observation_latency_bucket_seconds": (
                        OBSERVATION_LATENCY_BUCKET_SECONDS
                    ),
                },
            )
