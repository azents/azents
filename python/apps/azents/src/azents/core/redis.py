"""Redis client factory.

Prevents SSL errors (``APPLICATION_DATA_AFTER_CLOSE_NOTIFY``) that occur when
stale TLS connections remain in the pool and are reused in environments where
the server can close idle connections first, such as Elasticache Serverless Valkey.
"""

from redis.asyncio import Redis

# Validate connections idle for 30+ seconds with PING before use. This prevents
# stale connections after server close_notify from remaining in the pool and being
# reused. This setting is the **core** of this patch.
_HEALTH_CHECK_INTERVAL_SECONDS = 30

# Set bounded timeout so connection phase does not block indefinitely.
# NOTE: do not set socket_timeout (I/O timeout), because it breaks broker
# ``XREADGROUP BLOCK 0`` and PubSub ``listen``.
_SOCKET_CONNECT_TIMEOUT_SECONDS = 10


def create_redis_client(url: str) -> Redis:
    """Create Redis async client with idle-disconnect resilience.

    All Redis client creation in azents must go through this helper. Directly calling
    ``Redis.from_url(...)`` omits health checks and leaves clients vulnerable to
    idle-connection SSL errors in Elasticache Serverless environments.

    NOTE: automatic retry (``retry``) is intentionally not configured. Applying
    it broadly to non-idempotent commands like ``RPUSH`` / ``XADD`` /
    ``PUBLISH`` / ``SET NX`` can cause duplicate execution or dedup
    false-negatives, and blocking ``XREADGROUP`` can orphan PEL entries.
    Individual call sites handle retries as needed.

    :param url: Redis connection URL (``redis://`` or ``rediss://``)
    :return: Configured Redis async client
    """
    return Redis.from_url(
        url,
        health_check_interval=_HEALTH_CHECK_INTERVAL_SECONDS,
        socket_connect_timeout=_SOCKET_CONNECT_TIMEOUT_SECONDS,
    )
