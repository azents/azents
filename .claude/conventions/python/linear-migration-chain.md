---
title: "When reconciling an unmerged Alembic migration with a newer head, advance its `down_revision` to preserve one linear chain instead of adding a merge revision."
---

# Prefer Linear Alembic Migration Chains

A merge revision adds an unnecessary fork to a migration history when one of the migrations has not yet shipped.

- When an unmerged, unexecuted migration conflicts with a newer migration head, ALWAYS update its `down_revision` to the newer head and retain a single linear chain.
- AVOID creating an Alembic merge revision solely to reconcile migrations that have not been applied to any environment.
- NEVER modify a migration that has already run in an environment; use a generated merge revision when independent heads must both remain valid deployment history.

## Bad

```python
# A and B are both unexecuted migrations from the same predecessor.
down_revision = ("migration_a", "migration_b")
```

## Good

```python
# B remains unexecuted, so advance it after A.
# migration_b.py
down_revision = "migration_a"
```
