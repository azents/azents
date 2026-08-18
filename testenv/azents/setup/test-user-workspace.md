---
id: test-user-workspace
summary: Create new azents user and workspace, record in state.json
handler: testenv/setup_handlers/test_user_workspace.py
scope: run
requires: []
provides:
  - user.email
  - user.access_token
  - user.refresh_token
  - ws.handle
  - ws.name
idempotent: false
verify: |
  python3 -c "
  import json, os, subprocess, sys
  state = json.loads(open(os.environ['STATE_FILE']).read())
  handle = state.get('ws', {}).get('handle')
  if not handle:
      sys.exit(1)
  r = subprocess.run(
      ['docker', 'exec', 'azents-testenv-db-1',
       'psql', '-U', 'azents', '-d', 'azents', '-tA', '-c',
       f\"SELECT 1 FROM workspaces WHERE handle = '{handle}' LIMIT 1;\"],
      capture_output=True, text=True,
  )
  sys.exit(0 if r.stdout.strip() == '1' else 1)
  "
llm_key_required: false
created: 2026-04-11
---

# setup: test-user-workspace

Create a new Azents user and workspace and record their identifiers and authentication values in the fixture state. This setup is the base dependency for the `agent-basic` fixture.

## Provides / Requires

- `requires`: none
- `provides`: `user.email`, `user.access_token`, `user.refresh_token`, `ws.handle`, `ws.name`
- `idempotent: false`

## Run

Run the setup through its owning fixture command:

```bash
cd testenv/azents
uv run testenv fixture up agent-basic --json
```

The handler creates the user and workspace through the testenv client and stores the resulting values in `state.json`.

## Verify

The verification probe reads `ws.handle` from `state.json` and checks that the workspace exists. If verification fails, reset and recreate the fixture:

```bash
uv run testenv fixture reset agent-basic --json
uv run testenv fixture up agent-basic --json
```
