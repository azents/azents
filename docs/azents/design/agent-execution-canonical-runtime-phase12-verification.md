---
title: "Agent Execution Canonical Runtime Phase 12 Verification"
created: 2026-05-28
updated: 2026-05-28
tags: [backend, engine, qa]
---

# Agent Execution Canonical Runtime Phase 12 Verification

## Scope

This report records the verification evidence for the canonical agent execution runtime stack.
It covers the canonical transcript/runtime implementation, production canonical engine switch,
legacy SDK/raw LiteLLM cleanup, and testenv substrate readiness. Live provider verification is
optional and is not included because it requires credentials.

## Local Verification

| Check | Result |
| --- | --- |
| `cd python/apps/azents && uv run pytest src/azents/runtime -q` | PASS: 654 passed, 4 warnings |
| `cd python/apps/azents && uv run pyright` | PASS: 0 errors |
| `cd python/apps/azents && uv run pytest src/azents/runtime/canonical src/azents/engine/context/compaction_test.py src/azents/engine/tools/subagent_test.py -q` | PASS: 33 passed, 3 warnings |
| `cd testenv/azents && uv run pytest testenv/tests -q` | PASS: 131 passed, 16 warnings |
| legacy SDK/raw LiteLLM reference scan under `python/apps/azents` | PASS: no matches outside lockfile exclusions |
| `openai-agents` dependency scan in `python/apps/azents/pyproject.toml` and `uv.lock` | PASS: no matches |

## PR CI Evidence

| PR | Scope | Evidence |
| --- | --- | --- |
| #4112 | production canonical engine switch | Unit/type/lint/build checks pass after `9163abb4c`; deterministic E2E is still running at report creation time |
| #4113 | legacy SDK/raw LiteLLM cleanup | CI started after PR creation; local runtime and pyright checks pass before publish |

## E2E Matrix Status

| Scenario | Status | Evidence |
| --- | --- | --- |
| Text-only user turn completes | Covered by deterministic E2E CI | #4112 `azents-e2e deterministic` job |
| Client tool run completes | Covered by deterministic E2E CI | #4112 `azents-e2e deterministic` job |
| Parallel client tools complete | Covered by runtime integration/unit tests | `src/azents/runtime -q` |
| Background tool returns initial result | Covered by runtime integration/unit tests | `src/azents/runtime -q` |
| Stop during model stream | Covered by runtime integration/unit tests | `src/azents/runtime -q` |
| Stop during tool execution | Covered by runtime integration/unit tests | `src/azents/runtime -q` |
| Stale run recovery | Covered by runtime integration/unit tests | `src/azents/runtime -q` |
| Manual compact | Covered by compaction tests | `src/azents/engine/context/compaction_test.py -q` |
| Subagent run | Covered by subagent tests | `src/azents/engine/tools/subagent_test.py -q` |
| UI phase states | Covered by deterministic E2E CI and run phase tests | #4112 E2E plus runtime tests |

## Fixes Applied During Verification

- #4112 CI failure was fixed by preserving canonical engine model input context and routing deterministic OpenAI provider calls through `AZ_OPENAI_BASE_URL`.
- Phase 11 cleanup preserved message rendering and compaction summary behavior after removing SDK/raw LiteLLM modules.

## Remaining Non-Blocking Follow-Ups

- Live provider verification remains optional and must skip without credentials.
- Hosted/provider builtin tool support remains tracked in GitHub issue #4100.
