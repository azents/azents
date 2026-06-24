---
title: Use plain member names for injected collaborators by default; add underscore prefixes, Protocols, or ABCs only when there is a concrete need.
---

# Avoid Underscore Dependency Fields

Underscore prefixes are not an interface boundary. Do not add extra indirection just to make an injected collaborator look hidden.

- PREFER plain member names for constructor-injected collaborators, such as `self.repository` or `self.publisher`
- AVOID `self._repository` / `self._publisher` unless there is a specific collision, backing-field, cache, or implementation-detail reason
- AVOID introducing a `Protocol` or ABC just because a collaborator is public on `self`
- PREFER a `Protocol` or ABC only when the class truly needs a smaller interface boundary than the concrete dependency provides

## Bad

```python
class UserStopFinalizer:
    def __init__(self, repository: AgentRunRepository) -> None:
        self._repository = repository
```

## Good

```python
class UserStopFinalizer:
    def __init__(self, repository: AgentRunRepository) -> None:
        self.repository = repository
```

## Good

```python
class RunStateStore(Protocol):
    async def mark_idle(self, session_id: str) -> None: ...


class UserStopFinalizer:
    def __init__(self, store: RunStateStore) -> None:
        self.store = store
```
