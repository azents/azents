---
title: Prefer constructor-injected collaborators over creating instances in __post_init__; if dataclass initialization becomes complex, write an explicit __init__ instead.
---

# Dependency Injection Over Post Init

인스턴스 생성은 의존성 주입을 기본으로 삼고, dataclass는 생성자 작성 편의성을 위해서만 사용합니다.

- PREFER collaborator/service 인스턴스를 생성자 인자로 명시적으로 주입
- PREFER dataclass를 단순 생성자 boilerplate 제거 용도로만 사용
- AVOID `__post_init__`에서 상태 멤버나 collaborator를 초기화하기 위해 새 인스턴스를 생성
- PREFER dataclass 사용 때문에 초기화 코드가 복잡해지면 dataclass를 포기하고 명시적 `__init__` 작성
- EXCEPTION: 자기 자신의 bound method처럼 인스턴스가 생성된 뒤에만 연결 가능한 callback wiring은 `__post_init__`에 남길 수 있음

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
