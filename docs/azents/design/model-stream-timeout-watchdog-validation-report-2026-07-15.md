---
title: "Model stream timeout watchdog validation report"
created: 2026-07-15
tags: [backend, engine, testenv, testing]
document_role: supporting
document_type: supporting-validation-report
migration_source: "docs/azents/design/model-stream-timeout-watchdog-validation-report-2026-07-15.md"
---

# Model Stream Timeout Watchdog Validation Report

## Scope

This report validates the Model Stream Timeout Watchdog implementation described in:

- `docs/azents/design/model-stream-timeout-watchdog.md`
- `docs/azents/adr/0145-model-stream-parsed-event-idle-and-attempt-bounds.md`
- `docs/azents/adr/0146-serialize-live-partial-attempts-and-unify-tool-projection-identity.md`

The validation covers failed-attempt live partial isolation, the common stream watchdog, timeout retry metadata, caller-specific behavior, and public-path resynchronization. Preparing-tool UI and broader incremental streaming remain outside this feature.

## Environment

- Repository validation date: 2026-07-15
- Python: 3.14.6
- Deterministic provider fixture: `ghcr.io/copilotkit/aimock:1.36.1`
- E2E timeout overrides:
  - connect: 2 seconds
  - parsed-event idle: 0.5 seconds
  - absolute attempt: 1.5 seconds
  - close grace: 0.25 seconds
- Failed-run E2E backoff: 1 second fixed
- External credentials: none

AIMock 1.36.1 is required because its JSON fixture schema supports `recordedTimings`, which creates a deterministic post-prefix inter-event stall. The earlier 1.24.1 image supported only uniform `ttft` and `tps` timing and could not independently validate an idle timeout after visible output.

## Validation Matrix

| Scenario | Fixture mechanism | Product-path assertions |
| --- | --- | --- |
| No initial parsed event | First attempt uses a 1-second TTFT | Retry succeeds; no failed assistant output or timeout error is durable. |
| Idle after visible prefix | Recorded timings emit the first text delta, then pause for 1 second | Prefix becomes visible, is removed before retry state, and is absent from durable history. |
| Parsed events refresh idle | 20 events per second for longer than 0.5 seconds | The response completes without timeout even though total duration exceeds the idle deadline. |
| Absolute attempt cap | Long 20-events-per-second response | Frequent activity cannot extend the attempt past 1.5 seconds. |
| Retry recovery | Sequence-selected second response succeeds | One Run completes without a durable timeout error. |
| Retry exhaustion | Four sequence-selected stalled responses | Terminal attempt history contains attempts 1-4 with transient `model_stream_idle_timeout` codes. |
| User Stop race | Slow active response with visible partial | Public Stop wins, preserves the valid partial, and creates no timeout retry. |
| Retry resynchronization | REST live state, subscribed WebSocket, and real browser reload | Failed partial is absent from REST retry state, its exact live event ID is removed over WebSocket before retry publication, and it does not reappear after browser reload. |
| Compaction timeout | Manual `/compact` command with four stalled summary calls | Existing failed-run retry boundary is used and no compaction summary is committed. |
| Session title timeout | Stalled best-effort title call | Completed agent output remains successful and the deterministic initial title remains `auto_initial`. |

All product state is created and inspected through public API, WebSocket, and browser paths. The suite does not write PostgreSQL or Redis directly.

## Commands and Results

### Backend implementation phases

The implementation branches passed the complete backend quality gate:

```console
cd python/apps/azents
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

Phase 1 result: 1,267 passed and 389 skipped.

Phase 2 result: 1,281 passed and 389 skipped. Dedicated deterministic unit tests cover connect classification, parsed-event idle reset and timeout, absolute cap, User Stop priority, early consumer close, late-handle cleanup, cleanup registry adoption, typed metadata, and bounded shutdown drain.

### E2E static validation

```console
cd testenv/azents/e2e
python -m json.tool src/support/aimock_fixtures/agents_md_loader.json
npx -y -p @copilotkit/aimock@1.36.1 llmock -p 4019 -h 127.0.0.1 \
  -f src/support/aimock_fixtures --strict --validate-on-load
uv run ruff format src/tests/azents/public/test_model_stream_watchdog.py \
  src/tests/azents/public/test_agent_execution_persistence.py src/tests/conftest.py
uv run ruff check src/tests/azents/public/test_model_stream_watchdog.py \
  src/tests/azents/public/test_agent_execution_persistence.py src/tests/conftest.py
uv run pyright
uv run pytest --collect-only -q \
  src/tests/azents/public/test_model_stream_watchdog.py
git diff --check
```

Result: AIMock loaded and validated all 90 fixtures, Ruff passed, Pyright reported 0 errors, and eight watchdog E2E tests collected. A direct streamed Responses probe observed the idle-after-prefix fixture's first text delta at 0.006 seconds and its second delta at 1.006 seconds, confirming that the visible prefix precedes a deterministic gap longer than the 0.5-second idle deadline. Additional probes confirmed that the system-message-specific title and compaction fixtures produce their first event after approximately 1 second, while the pre-existing compaction fixture still matches and responds immediately.

### Local E2E execution

A focused local test execution reached fixture setup but could not start containers because the runtime has no `/var/run/docker.sock`. The setup error was `docker.errors.DockerException` caused by `FileNotFoundError`; no E2E assertion ran. This is an environment blocker rather than behavioral evidence, so the deterministic E2E suite remains required in pull-request CI and must pass before merge approval is requested.

## Implementation-to-Spec Comparison

| Behavior | Implementation | Current living spec | Action |
| --- | --- | --- | --- |
| Completed provider output is required before durable model output | Enforced by the normalizer and terminal validation | Documented in `agent-execution-loop.md` | No drift. |
| Incomplete tool calls are never admitted | Enforced by normalizer and tool admission | Documented in `agent-execution-loop.md` | No drift. |
| Live model partials are non-durable and reconstructable | Enforced by live projection storage | Partially documented as UI-only streaming | Spec promotion must state failed-attempt discard and retry ordering. |
| User Stop may retain valid partial assistant text | Preserved by the interruption path | Documented in `agent-execution-loop.md` | Spec promotion should add watchdog precedence explicitly. |
| Failed attempts discard live model partials before retry publication | Enforced by serialized discard and executor ordering | Not yet documented | Add in spec-promotion PR. |
| Connect, parsed-event idle, and absolute attempt bounds | Enforced for sampling, compaction, and title generation | Not yet documented | Add policy ownership and defaults in spec-promotion PR. |
| Every parsed provider event refreshes idle equally | Enforced without semantic event inspection | Not yet documented | Add in spec-promotion PR. |
| Timeout failures are transient and retain stable codes | Enforced in retry classification and terminal metadata | Generic retry behavior is documented; timeout codes are not | Add codes and caller-specific consequences in spec-promotion PR. |
| Non-cooperative provider cleanup remains process-owned and bounded | Enforced by cleanup registry and worker shutdown drain | Not yet documented | Add lifecycle and shutdown bounds in spec-promotion PR. |
| Compaction timeout uses the Run retry boundary; title timeout is best-effort | Enforced at caller boundaries | Not yet documented | Add caller-specific behavior in spec-promotion PR. |

No missing implementation was found in the approved watchdog scope. The identified documentation gaps are intentionally reserved for the next spec-promotion PR after CI-backed E2E execution succeeds.

## Remaining Gate

The validation PR is not complete until its deterministic E2E CI job passes with Docker and AIMock 1.36.1. Any fixture incompatibility or behavioral failure must be fixed in this PR or the responsible earlier phase, followed by rebasing dependent stack branches.
