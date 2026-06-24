---
title: "Provider Compatibility QA Report"
tags: [backend, engine, testenv]
created: 2026-05-03
updated: 2026-05-03
implemented: 2026-05-03
---

# Provider Compatibility QA Report

## Execution Environment

- Target branch: `test/provider-compat/testenv-qa`
- Test method: provider request compatibility pure unit/fake recorder coverage
- External provider smoke: excluded from default CI scope. ChatGPT OAuth real smoke is opt-in follow-up because of cost/credential dependency.

## Scenario Results

| ID | Verdict | Evidence |
|---|---|---|
| `TC-COMPAT-RESPONSES-001` | PASS | `test_default_rule_strips_openai_store_false_input_ids`, `test_strip_input_ids_removes_top_level_id_only` |
| `TC-COMPAT-RESPONSES-002` | PASS | original item id assertion preserved |
| `TC-COMPAT-METADATA-001` | PASS | foreign metadata strip / same provider preserve tests |
| `TC-COMPAT-CALLID-001` | PASS | call/output pair same normalized id test |
| `TC-COMPAT-ANTHROPIC-001` | PASS | empty content part removal test |
| `TC-COMPAT-MISTRAL-001` | DEFERRED-DOCUMENTED | follow-up after confirming actual SDK payload shape |
| `TC-COMPAT-DEEPSEEK-001` | DEFERRED-DOCUMENTED | follow-up after confirming actual SDK payload shape |
| `TC-COMPAT-SCHEMA-001` | PASS | Gemini/ref sibling schema sanitizer fixture tests |
| `TC-COMPAT-MEDIA-001` | PASS | unsupported image error text replacement test |
| `TC-COMPAT-CHAIN-001` | PASS | filter chain order test |

## Commands

```bash
cd python/apps/nointern
uv run ruff check --fix src/nointern/engine/sdk/filters src/nointern/engine/sdk/engine_adapter.py src/nointern/engine/sdk/filters_test.py
uv run ruff format src/nointern/engine/sdk/filters src/nointern/engine/sdk/engine_adapter.py src/nointern/engine/sdk/filters_test.py
uv run pyright
uv run pytest src/nointern/engine/sdk/filters_test.py
```

## Results

- ruff check: PASS
- ruff format: PASS
- pyright: PASS
- pytest filters: `30 passed`

## Remaining Risks

- Real provider smoke was not included in default CI because it depends on external credentials/cost.
- Mistral/DeepSeek message shape rules remain follow-up candidates.
