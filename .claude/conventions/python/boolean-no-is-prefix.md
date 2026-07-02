---
title: "Boolean column and field names do NOT take an `is_` prefix — `enabled`, `available`, `archived` (not `is_enabled`, `is_available`, `is_archived`)."
---

# Boolean Names: No `is_` Prefix

The convention is to drop the `is_` prefix on booleans. The type already says it's a bool; the prefix is redundant. Applies to SQLAlchemy columns, Pydantic fields, and dataclass fields.

- ALWAYS name booleans as the adjective alone: `enabled`, `available`, `archived`, `verified`
- AVOID `is_enabled`, `is_available`, `is_archived`
- Preposition-free verbs (`has_`, `can_`) follow the same logic — drop them when the field is plainly an adjective; keep them when the verb form clarifies (e.g. `has_payment_method`)

## Bad

```python
class Agent(Base):
    is_enabled: Mapped[bool] = mapped_column(...)
    is_archived: Mapped[bool] = mapped_column(...)
```

## Good

```python
class Agent(Base):
    enabled: Mapped[bool] = mapped_column(...)
    archived: Mapped[bool] = mapped_column(...)
```
