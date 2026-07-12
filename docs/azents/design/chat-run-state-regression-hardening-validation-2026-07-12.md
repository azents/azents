---
title: "Chat Run State Regression Hardening Validation Report"
created: 2026-07-12
tags: [api, backend, chat, engine, frontend, testenv, process]
---

# Chat Run State Regression Hardening Validation Report

## Scope

This report validates the integrated stack through durable turn inference provenance. It covers opaque reasoning-effort preservation, live Run ordering and resilience, exact terminal correlation, Composer selection persistence, and historical token provenance.

## Environment

- Source stack head: `fix/chat-run-state-hardening-validation`, based on `fix/chat-run-state-hardening-turn-provenance`
- Python: repository-managed `uv` environments
- TypeScript: repository-managed `pnpm` workspace
- E2E infrastructure: unavailable locally because the Docker Unix socket is absent
- External provider credentials: not required; mandatory scenarios use deterministic fixtures

## Validation Results

| Area | Command | Result |
|---|---|---|
| Backend focused tests | `cd python/apps/azents && uv run pytest src/azents/engine/events/types_test.py src/azents/engine/events/execution_test.py src/azents/engine/events/engine_adapter_test.py src/azents/worker/run/executor_test.py` | Pass: 86 passed, 3 warnings |
| Backend types | `cd python/apps/azents && uv run pyright` | Pass: 0 errors, 0 warnings |
| Backend focused lint | `cd python/apps/azents && uv run ruff check <changed modules>` | Pass |
| Frontend types | `cd typescript && pnpm run typecheck --filter=@azents/web` | Pass |
| Frontend lint | `cd typescript && pnpm run lint --filter=@azents/web` | Pass |
| Frontend component build | `cd typescript && pnpm run build-storybook --filter=@azents/web` | Pass |
| E2E static checks | `cd testenv/azents/e2e && uv run ruff check src/tests/azents/public/test_per_prompt_inference_profile.py && uv run pyright src/tests/azents/public/test_per_prompt_inference_profile.py` | Pass after validation-branch changes |
| Deterministic focused E2E | `cd testenv/azents/e2e && uv run pytest -vv -m 'not live_external' src/tests/azents/public/test_per_prompt_inference_profile.py` | Blocked before test execution: Docker socket unavailable |
| Diff hygiene | `git diff --check` | Pass |

The focused E2E attempt produced four fixture-setup errors with the common root cause `docker.errors.DockerException` wrapping `FileNotFoundError(2, 'No such file or directory')` for the Docker Unix socket. These are environment setup failures rather than product assertion failures. Deterministic CI is the required runtime evidence.

## Validation Additions

The validation branch extends the deterministic model-listing fixture so the non-lightweight model advertises all backend-supported reasoning efforts: `none`, `minimal`, `low`, `high`, `xhigh`, and `max`.

The per-prompt inference E2E now:

- submits `xhigh` through the public input API;
- waits for the completed durable transcript;
- verifies the matching `turn_marker` preserves the exact target and raw effort;
- verifies the public model display name, effective context window, and automatic compaction threshold remain available after the Session becomes idle;
- verifies a second target with default effort records an independent turn snapshot;
- verifies physical provider selection, full model selection, and credentials are absent from the public marker payload.

## Primary Matrix Status

| Behavior | Evidence | Status |
|---|---|---|
| Expanded supported effort survives | Public API tests, raw frontend decoder/persistence stories, updated deterministic `xhigh` E2E | Static/local pass; E2E runtime awaiting CI |
| Unknown effort read compatibility | Frontend opaque-string decoder and persistence coverage, durable-provenance Storybook state using `future-ultra` | Pass |
| Running state through tool boundary | Live reducer and pending/Stop regression tests from implementation phases | Pass |
| Contradictory Session idle | Backend projection and frontend active-Run precedence tests | Pass |
| Stale REST response | Frontend observation-generation and request-epoch tests | Pass |
| Invalid non-null Run | Frontend snapshot decoder/reducer tests | Pass |
| Explicit Run absence | Frontend snapshot replacement tests | Pass |
| Stale terminal event | Backend live projector and frontend exact-Run reducer tests | Pass |
| Pre-Run unhandled failure | Session error reporter tests | Pass |
| Active-Run unhandled failure | Failed-run finalizer and executor tests | Pass |
| Selection after send | Focused ChatInput Storybook state | Pass |
| Selection after reload | Focused ChatInput Storybook state | Pass |
| Deleted selected target | Focused ChatInput Storybook state | Pass |
| Historical usage provenance | Engine marker tests, token indicator durable-provenance story, updated deterministic E2E | Static/local pass; E2E runtime awaiting CI |
| Historical marker compatibility | Payload decoding test and unavailable-provenance story | Pass |

## Implementation and Current-Spec Comparison

| Contract | Implementation | Current living spec | Promotion action |
|---|---|---|---|
| Reasoning effort is an opaque frontend string while backend submission validation remains authoritative | Implemented | Partially documented | Update Conversation and Agent Execution Loop specs |
| Invalid non-null live Run snapshots preserve the last valid Run; explicit null clears it | Implemented | Missing exact distinction | Update Chat Session Resync spec |
| Newer WebSocket observations cannot be overwritten by stale REST replacements | Implemented | Missing compound-state ordering contract | Update Chat Session Resync spec |
| Terminal events and live clears require exact `run_id` correlation | Implemented | Missing exact terminal identity invariant | Update Agent Execution Loop and Conversation specs |
| Generic pre-Run errors do not synthesize terminal Run events | Implemented | Partially documented | Update Agent Execution Loop spec |
| Composer draft and last-selected inference profile have separate persistence lifecycles | Implemented | Missing precedence and deletion fallback | Update Conversation spec |
| Each durable turn usage marker stores allowlisted inference provenance | Implemented | Usage exists but provenance is missing | Update Session Context Inspector and Agent Execution Loop specs |
| Historical markers without provenance remain valid and do not borrow current state | Implemented | Missing | Update Session Context Inspector spec |

No implementation gap was found during local static and focused validation. The remaining evidence gap is deterministic E2E runtime, which is CI-owned in this environment.

## Exit Criteria

Validation is complete when the validation PR's deterministic E2E job passes. Spec promotion may then update the identified living specs and mark the design implemented. Live-provider verification remains optional because the mandatory matrix uses deterministic fixtures and requires no external credentials.
