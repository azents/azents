---
title: "Treat Redis as optional: provide an equivalent non-Redis implementation and never depend on Redis availability, persistence, or HA for correctness."
---

# Keep Redis optional and non-authoritative

- ALWAYS provide equivalent behavior through a non-Redis implementation, normally an
  in-memory adapter.
- NEVER depend on Redis availability, persistence, HA, leader election, or retained keys
  for authorization, cleanup, recovery, or other correctness.
- Redis failure may make the service unavailable and in-flight work fail closed, but a
  newly empty Redis instance must let the service resume automatically without restoring
  old keys, streams, locks, or indexes.
- Rebuild required derived state from durable authority or start safely from empty state;
  never infer lost in-flight work as successful.

## Bad

```python
cleanup_leader = await redis.acquire_lock("cleanup")
```

## Good

```python
store = RedisStateStore(redis) if redis is available else InMemoryStateStore()
cleanup = StateIndependentCleanup(object_store)
```
