---
id: agent-dummy-key
summary: Create agent with dummy-key LLM integration and shell tool enabled
handler: testenv/setup_handlers/agent_dummy_key.py
scope: run
requires:
  - llm-provider-dummy
provides:
  - agent.id
  - agent.model_slug
idempotent: true
verify: |
  python3 -c "
  import json, os, sys
  state = json.loads(open(os.environ['STATE_FILE']).read())
  sys.exit(0 if state.get('agent', {}).get('id') else 1)
  "
llm_key_required: false
created: 2026-04-11
---

# setup: agent-dummy-key

## translated

Dummy key OpenAI integration translated default runtime setting translated usetranslated
agent translated createtranslated. LLM translated path (TC-CHAT-001) translated MCP toolkit path
(TC-MCP-001/002) translated translated verifytranslated translated.

## Provides / Requires

- `requires`: `llm-provider-dummy`, ``
- `provides`: `agent.id`, `agent.model_slug`
- `idempotent: false`

## run

`testenv/azents` translated cwd translated translated:

```bash
uv run python - <<'PYEOF'
import json, os
from testenv.client import build_client_from_env
from testenv.seed.types import User, Workspace, Integration

client = build_client_from_env()
state_file = os.environ["STATE_FILE"]
state = json.loads(open(state_file).read())

user = User(
    email=state["user"]["email"],
    access_token=state["user"]["access_token"],
    refresh_token=state["user"]["refresh_token"],
)
ws = Workspace(
    handle=state["ws"]["handle"],
    name=state["ws"]["name"],
    owner=user,
)
integration = Integration(
    id=state["integration"]["id"],
    workspace=ws,
    provider=state["integration"]["provider"],
    name=state["integration"]["name"],
)

SLUG = "gpt-4o-mini"
agent = client.agent.create(user, ws, integration, SLUG)

state.setdefault("agent", {}).update({
    "id": agent.id,
    "model_slug": SLUG,
})
open(state_file, "w").write(json.dumps(state, indent=2))
print(f"SEEDED agent.id={agent.id}")
PYEOF
```

## Verify

state.json translated `agent.id` exists check.

## translated

- `client.agent.create` translated default `shell_enabled=True` translated translated, workspace
  translated default runtime setting translated translated connectiontranslated. translated `` setup translated
  translated translated.
- Model slug translated `gpt-4o-mini` translated translated. translated modeltranslated agent translated translated translated
  setup translated.
