---
id: llm-provider-dummy
summary: Register dummy-key OpenAI integration and choose a current model for LLM-bypass pipeline tests
handler: testenv/setup_handlers/llm_provider_dummy.py
scope: run
requires:
  - test-user-workspace
provides:
  - integration.id
  - integration.provider
  - integration.name
  - integration.model_identifier
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

Create the dummy-key OpenAI integration used by the `agent-basic` fixture and wait for its initial integration-scoped catalog publication before choosing the exact first model through the public API. The bounded wait observes current sync state; terminal failure and successful-empty catalogs fail explicitly. The deterministic testenv model-listing path makes this setup independent from live LLM credentials.

## Provides / Requires

- `requires`: `test-user-workspace`
- `provides`: `integration.id`, `integration.provider`, `integration.name`, `integration.model_identifier`
- `idempotent: false`

## Run

Run the setup through its owning fixture command:

```bash
cd testenv/azents
uv run testenv fixture up agent-basic --json
```

The handler reconstructs the user and workspace from fixture state, creates an OpenAI integration using the deterministic testenv name, reads the current selectable catalog, and stores the actual selected model identifier under `integration` in `state.json`. An empty or mismatched catalog fails preparation instead of substituting an unrelated Workspace default.

## Verify

The verification probe succeeds when `state.json` contains `integration.id`. Because the setup is not idempotent, the fixture provider recreates the owning fixture when verification fails.
