---
title: "Pass dependencies (DB session, HTTP client, config) through constructor or function parameters — never reach for module-level globals or singletons inside business logic."
---

# Dependency Injection, No Global Singletons

Globals make services hard to test (every test needs to monkeypatch the global) and hide control flow (you can't tell from the signature what a function depends on).

- ALWAYS take dependencies via constructor (`__init__`) or function parameter
- AVOID module-level singletons and `get_X()` lookups inside business logic
- The composition root (FastAPI dependency tree, Temporal worker setup, CLI entrypoint) is the only place that wires concrete instances

## Bad

```python
db = create_engine(...)  # module-level

def list_users() -> list[User]:
    with db.begin() as conn:
        return conn.execute(...).all()
```

## Good

```python
class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(self) -> list[User]:
        return (await self._session.execute(...)).scalars().all()
```
