---
title: "In tests, use explicit synchronization or authoritative state instead of fixed sleeps or scheduler yields to establish ordering; reserve wall-clock waits for behavior whose contract is elapsed time."
---

# Synchronize Tests with Observable Boundaries

Fixed delays make test results depend on machine speed and scheduler timing instead of the behavior under test.

- ALWAYS establish ordering with events, barriers, queues, fake streams or clocks, or polling of authoritative API/UI state.
- AVOID sleeps, scheduler yields, retry delays, or enlarged timeouts as a way to let work settle.
- Timeouts may bound hangs, but they must not establish the success condition.
- Exception: use elapsed time when time itself is the contract, such as a TTL, deadline, grace period, or backoff. Prefer a fake clock when the tested layer permits one; use bounded real time only at an integration boundary.

## Bad

```python
start_work()
await asyncio.sleep(0.1)
assert work_finished()
```

## Good

```python
start_work()
await work_finished.wait()
assert authoritative_state() == "finished"
```
