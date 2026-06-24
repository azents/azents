---
title: "When adding Python fields or function parameters, make callers pass a value explicitly; if optional, prefer a required nullable type over a default."
---

# Required New Fields

Defaults hide callsites that were never audited. In this repo we own the callers, so a type-checker-visible signature break is usually safer than silently flowing `None`, `[]`, `0`, or another default through runtime behavior.

- PREFER new dataclass, Pydantic model, constructor, and function parameters without defaults
- PREFER `field: T | None` over `field: T | None = None` when the caller must consciously choose `None`
- AVOID adding defaults just to keep callsites compiling
- EXCEPTION: bag-of-options objects such as `Config` or `Options` classes whose purpose is partial caller selection

## Bad

```python
class EngineWorker:
    def __init__(
        self,
        broker: SessionBroker,
        live_event_store: LiveEventStore | None = None,
    ) -> None: ...
```

## Good

```python
class EngineWorker:
    def __init__(
        self,
        broker: SessionBroker,
        live_event_store: LiveEventStore | None,
    ) -> None: ...
```
