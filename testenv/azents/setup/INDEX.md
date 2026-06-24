# Fixture Setup Catalog

`agent-basic` fixture translated translated meta probe translated internaltranslated usetranslated setup substrate listtranslated.
translated QA translated setup translated translated runtranslated translated fixture/QA command translated translated translated.

## translated translated

Fixture provider translated setup DAG translated resolve translated translated translated setup translated next translated processtranslated.

1. `provides: []` translated `verify` none — translated runtranslated.
2. `provides: []` translated `verify` exists — verify success translated skip, failure translated idempotent translated translated run translated blocktranslated.
3. `provides` translated translated fixture-private state translated translated keytranslated translated checktranslated, translated translated verify/handler translated runtranslated.

## translated

<!-- AUTO-GENERATED:START -->
| id | provides | requires | idempotent | translated |
|---|---|---|---|---|
| `agent-dummy-key` | agent.id, agent.model_slug | llm-provider-dummy | ✓ | Create agent with dummy-key LLM integration and shell tool enabled |
| `llm-provider-dummy` | integration.id, integration.provider, integration.name, integration.model_config_id | test-user-workspace | ✗ | Register dummy-key OpenAI LLM integration and ModelConfig for LLM-bypass pipeline tests |
| `test-user-workspace` | user.email, user.access_token, user.refresh_token, ws.handle, ws.name | — | ✗ | Create new azents user and workspace, record in state.json |
<!-- AUTO-GENERATED:END -->

## translated setup translated translated

- fixture provider translated automated probe translated actualtranslated translated translated translated.
- translated translated translated translated legacy TC translated setup translated translated translated.
- translated translated `uv run python scripts/gen-setup-index.py` translated translated documenttranslated `AGENTS.md` translated translated.
