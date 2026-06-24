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

## translated

agent-basic fixture translated translated probe translated usetranslated **dummy api key** translated OpenAI
integration translated ModelConfig translated createtranslated. actual LLM call translated API/agent
setup pathtranslated dummy key translated translated checktranslated translated.

## Provides / Requires

- `requires`: `test-user-workspace`
- `provides`: `integration.id`, `integration.provider` (`"openai"`),
  `integration.name`, `integration.model_config_id`
- `idempotent: false`

## run

`testenv/azents` translated cwd translated translated:

```bash
uv run python - <<'PYEOF'
import json, os
from testenv.client import build_client_from_env
from testenv.seed.types import User, Workspace

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

integration = client.llm.create_integration(
    user,
    ws,
    name="__testenv_model_listing:deterministic-success",
)  # api_key defaultvalue = dummy
model_config_id = client.llm.create_model_config_from_first_candidate(
    user,
    ws,
    integration,
    label="Testenv default model",
)

state.setdefault("integration", {}).update({
    "id": integration.id,
    "provider": integration.provider,
    "name": integration.name,
    "model_config_id": model_config_id,
})
open(state_file, "w").write(json.dumps(state, indent=2))
print(f"SEEDED integration.id={integration.id} model_config.id={model_config_id}")
PYEOF
```

## Verify

state.json translated `integration.id` translated `integration.model_config_id` exists check.
DB reality translated none (API key translated dummy translated LLM call failuretranslated pipeline translated translated
eventtranslated translated translated translated translated).

## translated

- `create_integration` translated `api_key` defaultvaluetranslated `testenv/seed/llm.py` translated `sk-test-dummy`.
- deterministic listing fixture translated backend `AZ_TESTENV_API_ENABLED=true` translated
  translated integration translated translated.
- translated provider (anthropic, gemini translated) translated translated translated translated setup translated translated
  translated — translated setup translated OpenAI translated.
