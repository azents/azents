---
title: prefer replacement over modification
---

# Prefer replacement over modification

AI edits compound local drift when they preserve a misunderstood structure and keep adding patches to it.

- ALWAYS prefer replacing a narrow unit, such as a function, small class, or local module surface, when its responsibilities, control flow, or state model no longer match the intended behavior.
- ALWAYS preserve the surrounding public contract, call sites, migrations, and compatibility boundaries unless the task explicitly changes them.
- AVOID minimizing the diff by adding flags, branches, adapters, or special cases to code whose current shape is already wrong.
- Only replace when the expected behavior, invariants, or acceptance checks are clear enough to verify.

## Bad

```python
def should_run(reason: str, *, wake_up: bool, has_buffered_input: bool) -> bool:
    if wake_up:
        return True
    if reason == "retry":
        return True
    if has_buffered_input:
        return True
    return False
```

## Good

```python
def pending_work(inputs: RuntimeInputs) -> PendingWork:
    return PendingWork(
        should_run=inputs.has_command
        or inputs.has_buffered_input
        or inputs.has_actionable_events,
        promoted_messages=inputs.promote_buffered_input(),
    )
```
