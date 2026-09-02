---
title: "Interactive Runtime Terminal Phase 1 — Runner PTY and Protocol"
created: 2026-09-01
updated: 2026-09-01
tags: [terminal, runtime, runner, grpc, implementation]
---

# Interactive Runtime Terminal Phase 1 — Runner PTY and Protocol

## Phase Execution Plan

- Phase: `1 — Runner PTY and Terminal protocol`
- Branch/base: `feature/terminal-260901` → `origin/main`
- PR title: `Runtime Terminal [1/5]: Add Runner PTY and terminal protocol`
- PR boundary: Add the approved hidden Runner PTY capability, OS-neutral shared Terminal protocol, per-Terminal outbound gRPC client/server boundary, lifecycle enforcement, and deterministic tests without Public API, policy persistence, coordination, or Web exposure.
- Inputs: Confirmed `terminal-260901/REQ`, accepted `terminal-260901/ADR-D1`–`ADR-D6`, approved `terminal-260901/DESIGN` revision `1`, latest `origin/main` at phase start.
- Deliverables: `terminal.v1` Runner capability; typed Control open/terminate intents; one bidirectional Terminal RPC per active Terminal; Linux PTY backend; Runner-local Terminal registry; input deduplication; output resend evidence; resize/Ctrl-C; bounded lifecycle/quota enforcement; complete POSIX-session cleanup; hidden Control-side servicer boundary and tests.
- Non-goals: Public Terminal REST/WebSocket, Redis/in-memory Terminal coordination, Terminal policy fields, xterm.js UI, `shell_enabled` removal, E2E, Living Spec promotion, production Terminal open intent emission.
- Interfaces: Approved M3/M5/M6 wire and lifecycle contracts; `terminal.v1`; exact Runtime/Runner/Terminal generation registration; 16 KiB binary chunks; contiguous input sequence; highest-applied input evidence; cumulative output acknowledgement; two-minute data-stream grace with 30-second attempts; one RPC per Terminal.
- Approved Design mechanisms: `M3`, `M5`, `M6`, `M10`, `M12`
- Authority references: `terminal-260901/REQ-1`, `REQ-4`, `REQ-5`, `REQ-7`, `REQ-9`, `REQ-11`; `terminal-260901/ADR-D2`, `ADR-D3`, `ADR-D5`, `ADR-D6`; current Agent Runtime Control and Persistence Specs; Runtime portability and structured-logging conventions.
- Design delta: `None`
- Removal obligations: Do not reuse pipe `ExecutionProcess` as PTY; do not add PTY bytes to existing operation events or Chat contracts. Existing pipe process behavior remains.
- Absence verification: Static protocol inventory, focused tests, and diff inspection prove Terminal bytes exist only in the new Terminal RPC and PTY backend; existing process-operation tests remain unchanged and pass.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Shared Terminal wire and typed contracts | `/root/terminal-protocol-owner` | `proto/azents/runtime_control/v1/runtime_runner_control.proto`, new Terminal proto, `python/libs/azents-runtime-control/**` generated and handwritten Terminal contracts/tests | Approved Design | Control intents, per-Terminal stream messages, serializers, client/server Protocols | proto generation, Ruff, format, ty, focused/full library pytest |
| Runner PTY backend and registry | `/root/terminal-runner-owner` | new `python/apps/azents-runtime-runner/src/azents_runtime_runner/terminal*.py`, PTY child launcher, matching tests | Shared handwritten contract shapes; may begin with typed Protocol stubs and reconcile after generator output | PTY open/read/write/resize/wait, session-wide cleanup, input dedup/partial resume, output resend window, lifecycle/quota registry | Ruff, format, ty, focused Runner pytest including real Linux PTY probes |
| Runtime Control Terminal gRPC boundary | `/root` | new `python/apps/azents/src/azents/runtime/control_protocol/grpc/runner_terminal_server.py`, focused tests, bounded changes to gRPC server registration helpers | Shared proto | Authenticated generation-fenced stream registration and injected broker boundary; not publicly activated | Ruff, format, ty, focused backend gRPC tests |
| Runner integration | `/root` | `python/apps/azents-runtime-runner/src/azents_runtime_runner/main.py`, capability registration, bounded Control intent handler wiring, integration tests | Protocol and PTY registry | Hidden `terminal.v1` capability and on-intent stream startup; no stream without intent | Runner focused/full pytest, startup tests |
| Integration and phase validation | `/root` | phase-owned cross-path fixes only | All workstreams | Stable compile/test result and scope checkpoint | full affected Python quality checks and diff inventory |

- Integration order:
  1. Protocol owner defines proto fields, shared immutable types, and generated modules.
  2. Runner owner implements the PTY backend/registry against the approved shared interfaces.
  3. Primary agent implements Control servicer/broker boundary and Runner main/control-intent wiring.
  4. Primary agent resolves integration defects, runs complete affected checks, and freezes the diff for review.
- Independent review: `/root/terminal-reviewer` reviews the stable Phase 1 diff read-only against `REQ-1/4/5/7/9/11`, ADR-D2/D3/D5/D6, Design M3/M5/M6/M10/M12, this plan, process cleanup, duplicate-input safety, generation fencing, content logging, and protocol compatibility. Output is pass or bounded required corrections. Security/data-loss, material interface, Requirements/Design, and applicable convention corrections receive targeted re-review by the same reviewer.
- Final validation:
  - `cd python/libs/azents-runtime-control && uv run python scripts/generate_proto.py`
  - `cd python/libs/azents-runtime-control && uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -vv`
  - `cd python/apps/azents-runtime-runner && uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -vv`
  - `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run ty check --error-on-warning && uv run pytest -vv src/azents/runtime/control_protocol/grpc`
  - root `git diff --check` and static inventory for prohibited existing transports.
- Scope-drift check: Verify every Phase 1 deliverable is covered, no Public API/policy/Web/E2E work appears, no Terminal bytes enter Chat or operation streams, no Runtime lifecycle lock/wait is added, no compatibility fallback or new configuration surface is introduced, and `Design delta` remains `None`.
- Context checkpoint: Record final proto/capability names, PTY process/session ownership, reconnect/input/output evidence, cleanup proof, test commands/results, reviewer result, remaining Phase 2 interfaces, branch SHA, and PR link.
