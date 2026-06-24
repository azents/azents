---
title: "When consuming a closed Python union or discriminated union, prefer match with assert_never so new variants fail type checking instead of falling through."
---

# Exhaustive Union Match

Closed unions should make missing branches visible at type-check time, not as runtime fallback behavior.

- PREFER `match` when dispatching on every variant of a closed union
- ALWAYS call `assert_never(...)` in the default branch to preserve exhaustiveness
- AVOID broad fallback logging/ignoring for union variants that should be fully known
- EXCEPTION: filtering, probing, or partial handling code may use `isinstance` when it intentionally handles only some variants

## Bad

```python
def handle(message: BrokerMessage) -> None:
    if isinstance(message, SessionStopSignal):
        return
    if isinstance(message, SessionWakeUp):
        wake_up(message)
        return
    logger.warning("unsupported message")
```

## Good

```python
from typing import assert_never


def handle(message: BrokerMessage) -> None:
    match message:
        case SessionStopSignal():
            return
        case SessionWakeUp():
            wake_up(message)
        case _:
            assert_never(message)
```
