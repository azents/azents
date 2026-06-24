"""Worker health check HTTP server.

Lightweight aiohttp server for Kubernetes liveness/readiness probe.
Runs as separate asyncio task inside AgentWorker process.
"""

import logging

from aiohttp import web
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_DEFAULT_PORT = 8012


class HealthServer:
    """Lightweight health check server running inside Worker process.

    - ``/healthz`` — liveness probe (event loop response availability)
    - ``/readyz`` — readiness probe (Redis connection + shutdown status check)
    """

    def __init__(self, redis: Redis, *, port: int = _DEFAULT_PORT) -> None:
        self._redis = redis
        self._port = port
        self._shutting_down = False
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Start health check HTTP server."""
        app = web.Application()
        app.router.add_get("/healthz", self._liveness)
        app.router.add_get("/readyz", self._readiness)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "0.0.0.0", self._port)  # noqa: S104
        await site.start()
        logger.info("Health server started", extra={"port": self._port})

    async def stop(self) -> None:
        """Stop health check HTTP server."""
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
            await self._redis.ping()  # pyright: ignore[reportAttributeAccessIssue]  # redis.asyncio Redis type declaration is incomplete
        except Exception:
            logger.warning("Readiness check failed: redis unavailable", exc_info=True)
            return web.json_response(
                {"status": "not_ready", "reason": "redis unavailable"},
                status=503,
            )
        return web.json_response({"status": "ok"})
