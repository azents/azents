---
title: "Runtime Exec Process Tools Implementation Plan"
created: 2026-06-27
updated: 2026-06-27
tags: [backend, engine, runtime, toolkit]
---
# Runtime Exec Process Tools Implementation Plan

## Source Documents

- Design: [Runtime Exec Process Tools](./runtime-exec-process-tools.md)
- ADR: [ADR-0081: Runtime Exec Process Tools](../adr/0081-runtime-exec-process.md)

## Scope

This is the multi-phase implementation plan for Runtime Exec Process Tools. It defines stacked PR phase boundaries and requirement coverage. It is **not** a detailed per-phase implementation plan.

Current delivery stops after Phase 1 implementation. Later phases are listed only to show dependency direction and to keep Phase 1 reviewable without silently shrinking the full design.

## Stack Shape

```text
main
  <- runtime-exec-process [1/3]: Design docs
  <- runtime-exec-process [2/3]: Implementation plan
  <- runtime-exec-process [3/3]: Phase 1 — Generic tool-result metadata
```

Future work after this stack starts from Phase 2 and should open a new reviewed phase stack or continue the stack only after explicit approval.

## Requirement Mapping

| Requirement | Phase(s) | Notes |
| --- | --- | --- |
| R1. Replace `bash` with process tools | 4, 5 | Tool exposure and E2E catalog verification happen after protocol/runner support exists. |
| R2. Keep process ownership in Runner | 2, 3, 5 | Protocol models the boundary; runner manager owns handles. |
| R3. Add generic tool-result metadata | 1 | Current delivery target. No exec-specific engine-core behavior. |
| R4. Stream and buffer output in Runner | 2, 3, 5 | Runner implementation plus live event verification. |
| R5. Enforce bounded process lifecycle | 3, 5 | Runner cleanup policy and missing/expired observations. |
| R6. Keep Phase 1 pipe-based and defer PTY | 2, 3, 4 | Process protocol/schema must not expose `tty` in this feature series. |
| R7. Keep exec processes separate from background tool calls | 3, 4, 5 | Process tools must not return `BackgroundHandle` for running processes. |

## Phase Boundaries

### Phase 1 — Generic tool-result metadata

Covered requirements: R3

Purpose:

- Add the generic metadata carrier that later exec tool results will use.
- Keep Agent Engine core tool-agnostic and free of exec-specific result handling.

Boundary:

- Add `FunctionToolResult.metadata` as a JSON object with default `{}`.
- Preserve generic metadata on client tool result payloads.
- Propagate metadata from function tool handlers to client tool result events.
- Verify validation, defaulting, propagation, and model-visible output stability.

Input from previous phase:

- ADR/design decisions, especially ADR-0081-D4 and requirement R3.

Output for next phase:

- Tool handlers can return model-visible output plus generic structured metadata without adding engine-core exec branches.

Expected end state:

- Existing tools keep working without specifying metadata.
- Metadata is available to future exec tool implementations as a generic event/result carrier.
- No process protocol, runner process manager, `exec_command`, `write_stdin`, or `bash` replacement code is included yet.

Verification scope:

- Unit tests for the generic tool-result metadata contract.
- Static/type checks relevant to the changed Python modules.
- CI confirms no broader regressions.

Detailed file/module checklist and exact implementation steps are intentionally deferred to the Phase 1 implementation PR.

### Phase 2 — Runtime process protocol

Covered requirements: R2, R4, R6

Purpose:

- Define runner/control process operation contracts and result models.
- Preserve generation fencing and pipe-only scope.

Boundary:

- Add process start/write-poll request and reply contracts.
- Add structured process status/truncation/missing result shapes.
- Add protocol-level tests with mocked runner/control behavior.
- Do not implement a runner process manager yet.

Input from previous phase:

- Generic tool result metadata is available for future tool-layer rendering metadata.

Output for next phase:

- Runner implementation can consume stable process operation contracts.

Expected end state:

- Runtime-control and runner protocol types can represent process operations without exposing PTY/TTY.

Verification scope:

- Protocol unit tests and type/static checks.

### Phase 3 — Runner process manager

Covered requirements: R2, R4, R5, R7

Purpose:

- Implement runner-local process ownership and lifecycle.

Boundary:

- Add runner-owned process registry, stdout/stderr drain, bounded unread buffers, stdin write, poll, cleanup, and missing/expired observations.
- Keep process state in runner memory only.
- Do not expose final LLM tool surface yet unless required by test harnesses.

Input from previous phase:

- Stable process protocol contracts.

Output for next phase:

- Runtime toolkit can call runner process operations to implement model-visible tools.

Expected end state:

- Runner can start and continue pipe-based processes under bounded lifecycle and output limits.

Verification scope:

- Runner unit/integration tests for process lifecycle, drain, truncation, stdin, poll, cleanup, and missing behavior.

### Phase 4 — Runtime toolkit replacement

Covered requirements: R1, R6, R7

Purpose:

- Replace the model-visible runtime shell surface with `exec_command` and `write_stdin`.

Boundary:

- Add runtime toolkit tool schemas and handlers.
- Render model-visible exec result text in the runtime toolkit layer.
- Attach structured metadata through the Phase 1 generic boundary.
- Stop exposing `bash` as the LLM-visible runtime shell tool.
- Do not implement PTY/TTY or LLM-visible `terminate_process`.

Input from previous phase:

- Runner process manager and process protocol are implemented.

Output for next phase:

- Product behavior exists for E2E and live UI verification.

Expected end state:

- Agents can start, poll, and write to pipe-based processes using `exec_command` and `write_stdin`.

Verification scope:

- Runtime toolkit tests, event transcript tests, and targeted integration tests.

### Phase 5 — UI/live projection and E2E verification

Covered requirements: R1, R2, R4, R5, R7

Purpose:

- Verify product behavior E2E and ensure live process output can be projected safely.

Boundary:

- Project process output/lifecycle deltas for UI if required by the implementation.
- Run the E2E-primary verification matrix.
- Fill the design QA checklist with actual PASS evidence.
- Fix defects in their source phase and cascade changes forward.

Input from previous phase:

- Model-visible process tools are implemented.

Output for next phase:

- Verified implementation ready for spec promotion.

Expected end state:

- All required product scenarios pass with recorded evidence.

Verification scope:

- E2E/testenv product scenarios, runtime prerequisite snapshots, and live event traces.

### Phase 6 — Spec promotion and cleanup

Covered requirements: all implemented requirements

Purpose:

- Promote implemented behavior into living specs and remove temporary planning artifacts after implementation is complete.

Boundary:

- Update current specs to match implemented behavior.
- Set the design document `implemented` date.
- Remove temporary implementation plan documents in cleanup.

Input from previous phase:

- E2E/testenv verification evidence and final implementation diff.

Output:

- Current specs describe implemented behavior; temporary plans are removed.

## E2E Primary Verification Matrix

| Scenario | Requirements | Phase verified | Evidence |
| --- | --- | --- | --- |
| Quick command exits through `exec_command` | R1, R3 | 5 | Event transcript and final assistant answer using command output. |
| Long-running command yields and polls | R1, R2, R4, R5 | 5 | `exec_command` returns session id, later empty `write_stdin` returns output and exit. |
| Stdin interaction | R1, R4 | 5 | `write_stdin(chars=...)` changes process output. |
| Missing process observation | R2, R5 | 5 | Controlled runner cleanup/restart yields missing observation. |
| Large output truncation | R4 | 5 | Bounded retained output and truncation metadata/event evidence. |
| `bash` replacement | R1 | 5 | Tool catalog contains `exec_command`/`write_stdin` and omits `bash`. |
| No background completion injection | R7 | 5 | Event transcript shows no background completion injection for process exit. |

## testenv and prerequisite needs

- Live Agent Runtime prerequisite snapshot is required for product E2E.
- testenv support may need helper commands to create deterministic long-running commands and to trigger runner cleanup/restart.
- WebSocket/live event trace capture is required for output delta evidence.
- Phase 1 does not require runtime testenv because it is a generic event/tool-result contract change.

## Blockers and Open Questions

None for Phase 1.

Potential later-phase design checks:

- Exact process id format and cursor naming.
- Whether process live events need a new event kind or only stream projection payloads.
- UI batching/coalescing limits for very large output.
