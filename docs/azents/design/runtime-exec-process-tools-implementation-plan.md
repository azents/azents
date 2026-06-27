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

This is the multi-phase implementation plan for Runtime Exec Process Tools. It defines stacked PR phase boundaries and requirement coverage. It is **not** a detailed per-phase implementation plan; each implementation phase adds its own detailed phase plan in that phase PR.

This plan covers the full `ship-feature` stack through implementation, E2E/testenv verification, spec promotion, and cleanup.

## Stack Shape

```text
main
  <- runtime-exec-process [1/9]: Design docs
  <- runtime-exec-process [2/9]: Implementation plan
  <- runtime-exec-process [3/9]: Phase 1 — Generic tool-result metadata
  <- runtime-exec-process [4/9]: Phase 2 — Runtime process protocol
  <- runtime-exec-process [5/9]: Phase 3 — Runner process manager
  <- runtime-exec-process [6/9]: Phase 4 — Runtime toolkit replacement
  <- runtime-exec-process [7/9]: Phase 5 — E2E/testenv verification
  <- runtime-exec-process [8/9]: Phase 6 — Spec promotion
  <- runtime-exec-process [9/9]: Phase 7 — Cleanup
```

## Requirement Mapping

| Requirement | Phase(s) | Notes |
| --- | --- | --- |
| R1. Replace `bash` with process tools | 4, 5 | Tool exposure lands in Phase 4; E2E catalog behavior is verified in Phase 5. |
| R2. Keep process ownership in Runner | 2, 3, 5 | Protocol models the boundary; runner manager owns handles; verification proves missing behavior. |
| R3. Add generic tool-result metadata | 1, 5 | Phase 1 implements the generic carrier; Phase 5 verifies product scenarios using it. |
| R4. Stream and buffer output in Runner | 2, 3, 5 | Protocol and runner implementation land before E2E/live evidence. |
| R5. Enforce bounded process lifecycle | 3, 5 | Runner cleanup policy lands in Phase 3 and is verified in Phase 5. |
| R6. Keep initial implementation pipe-based and defer PTY | 2, 3, 4, 5 | Protocol/tool schemas avoid `tty`; verification confirms no PTY surface is exposed. |
| R7. Keep exec processes separate from background tool calls | 3, 4, 5 | Runner/toolkit implementation avoids `BackgroundHandle`; verification checks transcript behavior. |

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
- Add structured process status, output snapshot, truncation, and missing result shapes.
- Add protocol-level tests with mocked runner/control behavior.
- Keep the protocol pipe-based and do not expose `tty`.
- Do not implement a runner process manager yet.

Input from previous phase:

- Generic tool result metadata is available for future tool-layer rendering metadata.

Output for next phase:

- Runner implementation can consume stable process operation contracts.

Expected end state:

- Runtime-control and runner protocol types can represent process operations without exposing PTY/TTY.

Verification scope:

- Runtime-control protocol unit tests.
- Runner/control gRPC translation tests if protocol schemas change.
- Type/static checks for touched protocol modules.

### Phase 3 — Runner process manager

Covered requirements: R2, R4, R5, R7

Purpose:

- Implement runner-local process ownership, output buffering, stdin/poll, and bounded lifecycle.

Boundary:

- Add runner-owned process registry.
- Continuously drain stdout/stderr.
- Maintain bounded unread buffers and truncation facts.
- Implement stdin write and empty-input poll behavior at runner operation level.
- Implement cleanup for exit consumption, TTL, idle/max lifetime, runner shutdown, and quota pruning.
- Treat runner-local missing/expired/terminated states as process observations.
- Do not expose final LLM tool surface yet unless required by test harnesses.

Input from previous phase:

- Stable process protocol contracts.

Output for next phase:

- Runtime toolkit can call runner process operations to implement model-visible tools.

Expected end state:

- Runner can start and continue pipe-based processes under bounded lifecycle and output limits.
- Process handles and unread buffers remain runner-memory resources only.

Verification scope:

- Runner unit/integration tests for process lifecycle, drain, truncation, stdin, poll, cleanup, and missing behavior.
- Type/static checks for touched runner/control modules.

### Phase 4 — Runtime toolkit replacement

Covered requirements: R1, R6, R7

Purpose:

- Replace the model-visible runtime shell surface with `exec_command` and `write_stdin`.

Boundary:

- Add runtime toolkit tool schemas and handlers.
- Render model-visible exec result text in the runtime toolkit layer.
- Attach structured metadata through the Phase 1 generic boundary.
- Stop exposing `bash` as the LLM-visible runtime shell tool.
- Ensure running exec processes do not return `BackgroundHandle` and do not inject background completions.
- Do not implement PTY/TTY or LLM-visible `terminate_process`.

Input from previous phase:

- Runner process manager and process protocol are implemented.

Output for next phase:

- Product behavior exists for E2E and live UI verification.

Expected end state:

- Agents can start, poll, and write to pipe-based processes using `exec_command` and `write_stdin`.
- Existing runtime unavailable/deadline/cancel paths continue to produce tool observations/errors consistently with other runtime-backed tools.

Verification scope:

- Runtime toolkit tests.
- Event transcript/lowering tests.
- Targeted integration tests for tool catalog and process operation wiring.

### Phase 5 — E2E/testenv verification

Covered requirements: R1, R2, R3, R4, R5, R6, R7

Purpose:

- Verify product behavior E2E and ensure live process output can be projected safely.

Boundary:

- Add or update E2E/testenv fixture support required for deterministic process scenarios.
- Run the E2E-primary verification matrix.
- Capture runtime prerequisite snapshots and live event/tool transcript evidence.
- Fill the design QA checklist with actual PASS evidence.
- Strictly compare implemented behavior against related current specs and record spec-promotion inputs.
- Fix defects in their source phase and cascade changes forward.

Input from previous phase:

- Model-visible process tools are implemented.

Output for next phase:

- Verified implementation ready for spec promotion.

Expected end state:

- All required product scenarios pass with recorded evidence.
- No QA checklist item remains `TBD`, `SKIP`, `FAIL`, or `BLOCKED` unless a user-only external action is explicitly escalated.

Verification scope:

- E2E/testenv product scenarios.
- Runtime prerequisite snapshots.
- Tool call/result event transcript evidence.
- Live output event traces where live projection behavior is implemented.
- Final regression run after fixes.

### Phase 6 — Spec promotion

Covered requirements: all implemented requirements

Purpose:

- Promote implemented behavior into living specs.

Boundary:

- Update affected current specs under `docs/azents/spec/`.
- Add a new flow/domain spec only if the implemented behavior does not fit existing specs.
- Remove or integrate stale current-spec statements that no longer describe the implementation.
- Set the feature design document `implemented` date to the promotion date.
- Ensure the design QA checklist contains final PASS execution records before promotion.

Input from previous phase:

- E2E/testenv verification evidence and final implementation diff.

Output for next phase:

- Current specs describe implemented behavior.
- Temporary planning artifacts are ready for cleanup.

Expected end state:

- Spec docs, implemented design, and code agree.

Verification scope:

- `scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`.
- Spec/code strict comparison evidence from Phase 5.

### Phase 7 — Cleanup

Covered requirements: cleanup only

Purpose:

- Remove temporary planning artifacts after spec promotion.

Boundary:

- Delete the multi-phase implementation plan and phase implementation plans created for this feature.
- Regenerate docs index.
- Do not include product behavior, spec, or design changes.

Input from previous phase:

- Implemented design has `implemented` date and living specs are updated.

Output:

- Repository no longer carries temporary plan documents for the completed feature.

Expected end state:

- Source of truth is code + implemented design + current specs.

Verification scope:

- Docs index check.
- Diff review confirming cleanup-only changes.

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
| No PTY surface | R6 | 5 | Tool schema evidence shows no `tty` parameter and no PTY/resize behavior in Phase 1 implementation. |

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
