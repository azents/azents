"""create_redis_client tests."""

from typing import Any

from redis.asyncio import Redis

from azents.core.redis import create_redis_client


def _connection_kwargs(client: Redis) -> dict[str, Any]:
    """Fetch connection_pool kwargs from Redis client.

    ``connection_pool`` is a public redis-py attribute, but local type stubs do
    not declare it, so suppress pyright access error.
    """
    pool = client.connection_pool  # pyright: ignore[reportAttributeAccessIssue]  # stub not declared
    return pool.connection_kwargs


class TestCreateRedisClient:
    """Verify resilience settings are applied to Redis client."""

    def test_health_check_interval_is_set(self) -> None:
        """health_check_interval=30s preemptively blocks stale idle connections."""
        client = create_redis_client("redis://localhost:6379")
        kwargs = _connection_kwargs(client)
        assert kwargs["health_check_interval"] == 30

    def test_socket_connect_timeout_is_bounded(self) -> None:
        """socket_connect_timeout bounds the connection phase."""
        client = create_redis_client("redis://localhost:6379")
        kwargs = _connection_kwargs(client)
        assert kwargs["socket_connect_timeout"] == 10

    def test_socket_timeout_is_not_set(self) -> None:
        """I/O timeout (socket_timeout) is unset because it breaks blocking commands."""
        client = create_redis_client("redis://localhost:6379")
        kwargs = _connection_kwargs(client)
        assert kwargs.get("socket_timeout") is None

    def test_no_automatic_retry(self) -> None:
        """Automatic retry is intentionally not configured.

        This prevents duplicate execution of non-idempotent commands such as
        RPUSH/XADD/PUBLISH/SET NX and PEL orphaning in blocking XREADGROUP.
        """
        client = create_redis_client("redis://localhost:6379")
        kwargs = _connection_kwargs(client)
        retry = kwargs.get("retry")
        # When retry is not None, retry count must be <= 0; redis-py default can be
        # an empty Retry object with retries=-1.
        if retry is not None:
            assert retry._retries <= 0
