---
id: llm-provider-dummy
summary: Register dummy-key OpenAI LLM integration and ModelConfig for LLM-bypass pipeline tests
handler: testenv/setup_handlers/llm_provider_dummy.py
scope: run
requires:
  - test-user-workspace
provides:
  - integration.id
  - integration.provider
  - integration.name
  - integration.model_config_id
idempotent: false
verify: |
  python3 -c "
  import json, os, sys
  state = json.loads(open(os.environ['STATE_FILE']).read())
  sys.exit(0 if state.get('integration', {}).get('id') else 1)
  "
llm_key_required: false
created: 2026-04-11
---

# setup: llm-provider-dummy

Create the dummy-key OpenAI integration and ModelConfig used by the `agent-basic` fixture. The deterministic testenv model-listing path makes this setup independent from live LLM credentials.

## Provides / Requires

- `requires`: `test-user-workspace`
- `provides`: `integration.id`, `integration.provider`, `integration.name`, `integration.model_config_id`
- `idempotent: false`

## Run

Run the setup through its owning fixture command:

```bash
cd testenv/azents
uv run testenv fixture up agent-basic --json
```

The handler reconstructs the user and workspace from fixture state, creates an OpenAI integration using the deterministic testenv name, creates a ModelConfig from the first available candidate, and stores the resulting identifiers under `integration` in `state.json`.

## Verify

The verification probe succeeds when `state.json` contains `integration.id`. Because the setup is not idempotent, the fixture provider recreates the owning fixture when verification fails.
