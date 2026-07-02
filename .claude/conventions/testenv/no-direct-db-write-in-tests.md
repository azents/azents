---
title: "Test scenarios, runners, and helpers MUST NOT INSERT/UPDATE/DELETE directly against the database — reproduce state via the user-facing path (UI, API, slash command, OAuth flow). Cleanup SQL (DELETE FROM) inside `scenarios/setup/db-reset-*` is the sole exception."
---

# Tests Reproduce State via User Paths, Not Direct DB Writes

A direct `INSERT INTO ...` skips ORM hooks, audit log writes, validation, and the actual code path the user takes. Schema drift then produces tests that pass while production breaks.

- ALWAYS reproduce state by exercising the user path (slash command, button click, signed POST, OAuth flow)
- SELECT for verification is fine
- INSERT/UPDATE/DELETE outside `scenarios/setup/db-reset-*` is forbidden

## Bad

```python
# Binding a Slack channel by direct DB write
async with session.begin():
    await session.execute(
        sa.text("INSERT INTO slack_channel_bindings (...) VALUES (...)"),
    )
```

## Good

```python
# Bind via the same handler the slash command/button uses
await connect_agent_via_signed_post(
    channel_id=ch.id,
    agent_id=agent.id,
    signing_secret=signing_secret,
)
```

## Cleanup exception

Allowed inside `scenarios/setup/db-reset-*` — these reset the world to a clean state before the user-path actions run.
