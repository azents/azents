---
title: "Session-scoped Toolkit Lifecycle Verification 2026-05-29"
created: 2026-05-29
updated: 2026-05-29
tags: [backend, engine, toolkit, qa]
---

# Session-scoped Toolkit Lifecycle Verification 2026-05-29

## Scope

This report records verification evidence for the session-scoped toolkit lifecycle
stack through phase 6.

Covered implementation PRs:

- `toolkit-session-lifecycle [3/9]`: lifecycle registry
- `toolkit-session-lifecycle [4/9]`: worker session wiring
- `toolkit-session-lifecycle [5/9]`: current-turn Schedule/Subagent binding
- `toolkit-session-lifecycle [6/9]`: actor-keyed credential reuse guard and runtime
  env peer refresh

## Environment

- Date: 2026-05-29
- Repository: `<local-azents-repo>`
- Local Python runtime: project `uv` environments
- E2E stack: `testenv/azents/e2e` testcontainers fixtures
- Live provider credentials: not required; deterministic model/toolkit fixtures used

## Unit and Integration Evidence

Command:

```bash
cd python/apps/azents && uv run pytest \
  src/azents/worker/engine_test.py \
  src/azents/engine/tools/schedule_test.py \
  src/azents/engine/tools/builtin_test.py \
  src/azents/engine/session_toolkits_test.py \
  -q
```

Result:

```text
94 passed, 3 warnings in 4.45s
```

Coverage notes:

- `SessionToolkitLifecycle` enter/reuse/reconcile/partial-failure/cleanup behavior.
- `_SessionRunner` enter-before-update behavior.
- Same-session toolkit reuse by stable key.
- Registered toolkit re-keying when current actor changes.
- Schedule handlers using current `TurnContext.user_id`.
- Runtime shell env collection through managed peer snapshot.

## E2E Evidence

Command:

```bash
cd testenv/azents/e2e && uv run pytest \
  src/tests/azents/public/test_agent_execution_persistence.py \
  src/tests/azents/public/test_runtime_hooks.py \
  -q
```

Result:

```text
5 passed, 2 warnings in 36.44s
```

Covered product behavior:

- General chat response persists and survives REST reload.
- Tool call/result and follow-up assistant response persist.
- Manual compaction command completes and preserves subsequent history.
- Truncate/revert after run boundary remains compatible with canonical events.
- Runtime hook product-facing behavior still works with prepared toolkit snapshots.

File attachment command:

```bash
cd testenv/azents/e2e && uv run pytest \
  src/tests/azents/public/test_file_upload.py::TestUploadMessagePath::test_image_and_file_uploads_reach_model_input \
  -q
```

Result:

```text
1 passed, 2 warnings in 26.17s
```

Covered product behavior:

- Uploaded image and file attachments reach model input through chat message path.

## Static Quality Evidence

Commands run in implementation phases:

```bash
cd python/apps/azents && uv run ruff check \
  src/azents/worker/engine.py \
  src/azents/worker/engine_test.py \
  src/azents/engine/tools/builtin.py \
  src/azents/engine/tools/builtin_test.py

cd python/apps/azents && uv run pyright \
  src/azents/worker/engine.py \
  src/azents/worker/engine_test.py \
  src/azents/engine/tools/builtin.py \
  src/azents/engine/tools/builtin_test.py
```

Result:

```text
ruff: All checks passed.
pyright: 0 errors, 0 warnings, 0 informations
```

Docs command:

```bash
python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check
```

Result:

```text
passed
```

## QA Checklist Execution

First run does not block on delayed toolkit loading:

- What was checked: production path now enters session-managed toolkits before
  canonical `update_context()`.
- Evidence: `engine_test.py` enter-before-update regression and
  `session_toolkits_test.py` lifecycle tests.
- Result: Passed at unit/integration level.
- Remaining gap: deterministic delayed fake MCP E2E fixture is not present; this is
  explicitly carried as fixture work for future provider-specific E2E expansion.

Toolkit instances are session-scoped:

- What was checked: same session key reuses the first entered toolkit instance and
  exits it once on shutdown.
- Evidence: worker/session lifecycle tests.
- Result: Passed.

Run-scoped context does not go stale:

- What was checked: Schedule uses current turn user; Subagent wrapper creates the
  unified tool from current `TurnContext` with current parent run id, publish callback,
  stop checker, and actor.
- Evidence: schedule current-turn regression; pyright/ruff on worker subagent path.
- Result: Passed for Schedule with direct assertion; Subagent covered by code-level
  integration and existing E2E runtime execution path, not a dedicated subagent E2E.

Actor-sensitive credential lookup is current-turn based:

- What was checked: registered toolkit lifecycle key includes current actor, preventing
  cross-actor reuse of a user-bound instance.
- Evidence: worker regression for actor-keyed registered toolkit reuse.
- Result: Passed.

Runtime shell/env peer refs stay current:

- What was checked: RuntimeToolkit peer env providers are refreshed from the prepared
  managed snapshot, and env collection uses the `RuntimeEnvProvider` protocol.
- Evidence: builtin runtime shell env tests.
- Result: Passed.

Cleanup is structured and cancellation-safe:

- What was checked: lifecycle registry unwinds partial enter failure and closes active
  toolkits in reverse order.
- Evidence: `session_toolkits_test.py`.
- Result: Passed.

Canonical runtime behavior remains intact:

- What was checked: durable chat, tool call/result, manual compaction, truncate/revert,
  runtime hooks, and file attachment model input path.
- Evidence: E2E commands above.
- Result: Passed for deterministic available E2E coverage.

## Fixes Applied During Verification

- Removed now-unnecessary pyright ignore in `builtin_test.py` after runtime env peer
  generic coupling was replaced with `RuntimeEnvProvider`.
- Kept testenv live provider checks out of the required gate; deterministic fixtures
  covered the behavior needed by this phase.

## Residual Risk

There is no dedicated delayed-MCP E2E fixture yet. The production invariant is covered
by unit/integration tests that assert toolkit enter happens before `update_context()`,
which is the specific failure mode that triggered synchronous MCP fallback. A future
provider-focused E2E can add a fake delayed MCP server to measure phase timestamps
end-to-end.

Subagent has no dedicated E2E in the current deterministic suite. The worker wrapper now
constructs the tool from current `TurnContext`, and the path type-checks, but a product
subagent E2E remains useful coverage.
