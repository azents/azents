---
title: Prefer constructor-injected collaborators over creating instances in __post_init__; if dataclass initialization becomes complex, write an explicit __init__ instead.
---

# Dependency Injection Over Post Init

Default to dependency injection for instance construction. Use dataclasses only to reduce constructor boilerplate.

- PREFER injecting collaborator/service instances explicitly through constructor parameters
- PREFER using dataclasses only to remove simple constructor boilerplate
- AVOID creating new instances in `__post_init__` to initialize state members or collaborators
- PREFER dropping dataclasses and writing an explicit `__init__` when dataclass initialization becomes complex
- EXCEPTION: callback wiring that can only be connected after instance creation, such as a bound method on the instance itself, may remain in `__post_init__`

## Bad

```python
@dataclasses.dataclass
class EngineWorker:
    live_event_store: RedisLiveEventStore
    broadcast: WebSocketBroadcast
    _live_event_projector: LiveEventProjector = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self._live_event_projector = LiveEventProjector(
            live_event_store=self.live_event_store,
            broadcast=self.broadcast,
        )
```

## Good

```python
@dataclasses.dataclass
class EngineWorker:
    live_event_projector: LiveEventProjector


def get_engine_worker(...) -> EngineWorker:
    live_event_projector = LiveEventProjector(
        live_event_store=RedisLiveEventStore(worker_redis),
        broadcast=broadcast,
    )
    return EngineWorker(live_event_projector=live_event_projector, ...)
```

## Good

```python
class EngineWorker:
    def __init__(
        self,
        *,
        live_event_projector: LiveEventProjector,
        background_registry: BackgroundTaskRegistry,
    ) -> None:
        self.live_event_projector = live_event_projector
        self.background_registry = background_registry
```
