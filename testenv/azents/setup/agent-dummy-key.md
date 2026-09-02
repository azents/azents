---
id: agent-dummy-key
summary: Create agent with dummy-key LLM integration and default Runtime selection
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

Create an agent that uses the dummy-key OpenAI integration and the workspace's default Runtime settings. The setup stores the agent identifier and model slug in the fixture state.

## Provides / Requires

- `requires`: `llm-provider-dummy`
- `provides`: `agent.id`, `agent.model_slug`
- `idempotent: true`

## Run

Run the setup through its owning fixture command:

```bash
cd testenv/azents
uv run testenv fixture up agent-basic --json
```

The handler reconstructs the user, workspace, and integration from the fixture state, creates an agent with the `gpt-4o-mini` model slug, and records the identifiers under `agent` in `state.json`.

## Verify

The verification probe succeeds when `state.json` contains `agent.id`. The fixture provider owns cleanup and recreation when the probe fails.
