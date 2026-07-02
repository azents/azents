---
title: In RDB models, assign SQLAlchemy constraints and indexes to named class constants before listing them in `__table_args__` so schema objects are reusable and reviewable.
---

# RDB Index Constants

RDB models keep table constraints and indexes visible as named class attributes before wiring them into `__table_args__`.

- ALWAYS assign `sa.Index(...)` and `sa.UniqueConstraint(...)` objects to descriptive class constants such as `IX_WORKSPACE_ID` or `UQ_PROVIDER_MODEL_IDENTIFIER`.
- ALWAYS list those constants in `__table_args__` instead of constructing schema objects inline.
- This applies to handwritten RDB model files under `python/apps/azents/src/azents/rdb/models/`.

## Bad

```python
class RDBExample(RDBModel):
    __table_args__ = (
        sa.Index("ix_examples_workspace_id", "workspace_id"),
    )
```

## Good

```python
class RDBExample(RDBModel):
    IX_WORKSPACE_ID = sa.Index("ix_examples_workspace_id", "workspace_id")

    __table_args__ = (IX_WORKSPACE_ID,)
```
