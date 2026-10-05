---
title: "Declare SQLAlchemy indexes explicitly; allow descriptive aliases within PostgreSQL's 63-byte limit and schema relation namespace instead of requiring full column names."
---

# Explicit, Named Indexes

`mapped_column(index=True)` generates an implicit name SQLAlchemy chooses, which makes it hard to reference in migrations or production debugging.

- ALWAYS define indexes via an explicitly named `sa.Index(...)` in `__table_args__`.
- Prefer `ix_{table_name}_{column_name}` (or `_{col1}_{col2}` for composite indexes); full column expansion is not required.
- Allow descriptive aliases that identify the table and purpose, including composite, unique and partial indexes. For example, retain `ix_image_generation_catalog_entries_catalog_rank` and `uq_external_channel_agent_routes_single_connection`.
- Keep explicit names within 63 UTF-8 bytes and distinct from other relations in the same PostgreSQL schema. Distinguish different index purposes, uniqueness or predicates when the columns alone would give the same name.
- Keep the exact name consistent in the ORM, migrations and name-based consumers; do not rely on implicit truncation.
- Retain existing names that satisfy these rules. An alias alone does not require a rename migration.
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
