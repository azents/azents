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

## translated

translated azents user translated workspace translated translated, resulttranslated `state.json` translated
`user.*` / `ws.*` translated translated. translated test/setup translated base prerequisite.

## Provides / Requires

- `requires`: —
- `provides`:
  - `user.email`, `user.access_token`, `user.refresh_token`
  - `ws.handle`, `ws.name`
- `idempotent: false` — translatedrun translated translated user/ws translated translated state translated translated

## run

`testenv/azents` translated cwd translated translated:

```bash
uv run python - <<'PYEOF'
import json, os
from testenv.client import build_client_from_env

client = build_client_from_env()
user = client.auth.create_user()
ws = client.workspace.create(user)

state_file = os.environ["STATE_FILE"]
state = json.loads(open(state_file).read())
state.setdefault("user", {}).update({
    "email": user.email,
    "access_token": user.access_token,
    "refresh_token": user.refresh_token,
})
state.setdefault("ws", {}).update({
    "handle": ws.handle,
    "name": ws.name,
})
open(state_file, "w").write(json.dumps(state, indent=2))
print(f"SEEDED user={user.email} ws={ws.handle}")
PYEOF
```

## Verify

state.json translated `ws.handle` translated translated translated workspace translated DB translated existstranslated check.
frontmatter translated `verify` translated translated. Verify failure + idempotent: false translated
translated translatedruntranslated translated translated. current fixture state translated translated translated seed translated translated
`uv run testenv fixture reset agent-basic --json` translated
`uv run testenv fixture up agent-basic --json` translated runtranslated.

## translated

- `seed.auth.Auth.create_user` translated email translated `test-{unique()}@example.com` translated
  translated create. translated translated translated translated setup translated translated translated.
- Workspace handle translated `ws-{unique()}` translated translated create.
- tokentranslated translated API bearer auth translated translated, refresh_token translated translated refresh translated
  translated. translated token translated state translated save.
