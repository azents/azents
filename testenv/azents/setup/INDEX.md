# Fixture Setup Catalog

The `agent-basic` fixture uses this setup substrate internally. Product behavior verification belongs in E2E tests; these entries only prepare reusable fixture state.

## Execution model

The fixture provider resolves setup dependencies and evaluates each entry's verification probe before deciding whether to run its handler. Setup state is private to the owning fixture.

## Catalog

<!-- AUTO-GENERATED:START -->
| id | provides | requires | idempotent | summary |
|---|---|---|---|---|
| `agent-dummy-key` | agent.id, agent.model_slug | llm-provider-dummy | ✓ | Create agent with dummy-key LLM integration and default Runtime selection |
| `llm-provider-dummy` | integration.id, integration.provider, integration.name, integration.model_config_id | test-user-workspace | ✗ | Register dummy-key OpenAI LLM integration and ModelConfig for LLM-bypass pipeline tests |
| `test-user-workspace` | user.email, user.access_token, user.refresh_token, ws.handle, ws.name | — | ✗ | Create new azents user and workspace, record in state.json |
<!-- AUTO-GENERATED:END -->

Regenerate this catalog and the setup list in `AGENTS.md` after changing setup frontmatter:

```bash
cd testenv/azents
uv run python scripts/gen-setup-index.py
```
