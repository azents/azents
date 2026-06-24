---
name: azents-db-debug
description: "Database debugging tool for the azents project. Run non-interactive queries with shell.py -c to inspect database state. Use when: (1) inspecting/debugging azents database data, (2) checking runtime data such as events, sessions, and channels, or (3) the user asks to check the DB, inspect events, run a query, or look into the database."
---

# azents DB Debug

Run database queries with `shell.py -c` from the azents project directory.

## Execution

```bash
cd <local-azents-repo>/python/apps/azents && uv run python -m cli.shell -c "<python_code>"
```

## Available Variables

- `session` — SQLAlchemy `AsyncSession`
- `sa` — the `sqlalchemy` module
- `models` — azents RDB model module, such as `models.RDBToolkit` and `models.RDBAgent`

## Query Examples

### Raw SQL for table structure exploration or ad hoc queries

```bash
uv run python -m cli.shell -c "
rows = (await session.execute(sa.text(\"SELECT id, role FROM events ORDER BY created_at DESC LIMIT 5\"))).fetchall()
for r in rows:
    print(dict(r._mapping))
"
```

### SQLAlchemy ORM model usage (recommended)

```bash
uv run python -m cli.shell -c "
result = await session.execute(
    sa.select(models.RDBToolkit).where(models.RDBToolkit.slug == 'slack')
)
toolkit = result.scalar_one_or_none()
if toolkit:
    print('id:', toolkit.id)
    print('config:', toolkit.config)
    print('enabled:', toolkit.enabled)
"
```

### Inspect model list

```bash
uv run python -m cli.shell -c "
import inspect
for name, cls in sorted(inspect.getmembers(models)):
    if inspect.isclass(cls) and hasattr(cls, '__tablename__'):
        print(f'{name}: {cls.__tablename__}')
"
```

### JOIN query

```bash
uv run python -m cli.shell -c "
from sqlalchemy.orm import selectinload
result = await session.execute(
    sa.select(models.RDBAgentToolkit)
    .join(models.RDBToolkit, models.RDBAgentToolkit.toolkit_id == models.RDBToolkit.id)
    .where(models.RDBToolkit.slug == 'slack')
)
for row in result.scalars():
    print('agent_id:', row.agent_id, 'toolkit_id:', row.toolkit_id)
"
```

## Escaping Rules

- SQL `'` → `''` to avoid bash quoting conflicts
- `%` in `LIKE` → `%%` to avoid Python `%` formatting conflicts
- For long JSON, extract with `substring(col::text, 1, 500)` or `col->>'key'`
