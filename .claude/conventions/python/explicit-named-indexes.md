---
title: "Declare SQLAlchemy indexes explicitly in `__table_args__` with `sa.Index(\"ix_<table>_<column>\", ...)` — never use `mapped_column(index=True)` because the implicit name is opaque."
---

# Explicit, Named Indexes

`mapped_column(index=True)` generates an implicit name SQLAlchemy chooses, which makes it hard to reference in migrations or production debugging.

- ALWAYS define indexes via `sa.Index("ix_<table>_<column>", "column_name")` in `__table_args__`
- Naming convention: `ix_{table_name}_{column_name}` (or `_{col1}_{col2}` for composite)
- AVOID `mapped_column(..., index=True)`

## Bad

```python
class Team(Base):
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
```

## Good

```python
class Team(Base):
    workspace_id: Mapped[str] = mapped_column(
        sa.String(32),
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    __table_args__ = (
        sa.Index("ix_teams_workspace_id", "workspace_id"),
    )
```
