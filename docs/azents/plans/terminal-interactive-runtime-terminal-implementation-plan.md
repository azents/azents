---
title: "Interactive Runtime Terminal Implementation Plan"
created: 2026-09-01
updated: 2026-09-01
tags: [terminal, runtime, implementation, stacked-prs, testenv]
---

# Interactive Runtime Terminal Implementation Plan

- Requirements: [Interactive Runtime Terminal Requirements](../requirements/terminal-260901-interactive-runtime-terminal.md) (`terminal-260901/REQ`)
- ADR: [Interactive Runtime Terminal ADR](../adr/terminal-260901-interactive-runtime-terminal.md) (`terminal-260901/ADR`)
- Approved Design: [Interactive Runtime Terminal Design](../design/terminal-260901-interactive-runtime-terminal.md) revision `1` (`terminal-260901/DESIGN`)
- Approved mechanisms: `M1`–`M13`
- Design approval: Collaborative, requester, 2026-09-01
- Exact independent reviewer: `/root/terminal-reviewer`
- Design delta: `None`

## Delivery Shape

Use five stacked PRs matching `terminal-260901/ADR-D6` and Design M12. Every phase is buildable, reviewable, and fail closed. Create each PR before starting the next phase. Create the complete stack before monitoring CI. Do not merge without separate explicit requester approval.

PR titles use `Runtime Terminal [n/5]: <phase>`.

| Phase | Branch | Base | PR boundary | Approved mechanisms |
| --- | --- | --- | --- | --- |
| 1 | `feature/terminal-260901` | `main` | Runner PTY, shared Terminal protocol, hidden `terminal.v1` capability | M3, M5, M6, M12 |
| 2 | `feature/terminal-260901-backend` | Phase 1 | Policy persistence/resolution, volatile coordination, Terminal service, WebSocket backend | M1, M2, M4, M7, M8, M10, M12 |
| 3 | `feature/terminal-260901-web` | Phase 2 | Generated clients, xterm.js Session UI, responsive policy/settings surfaces | M2, M8, M9, M10, M12 |
| 4 | `feature/terminal-260901-shell-removal` | Phase 3 | Complete `shell_enabled` cutover and migration | M11, M12 |
| 5 | `feature/terminal-260901-e2e-specs` | Phase 4 | Required E2E, Living Specs, removal evidence, implementation markers, plan cleanup | M10, M12, M13 |

## Cross-Phase Interfaces

### Terminal identity and ownership

- Terminal IDs are independent from Session IDs.
- Initial singleton is one active Terminal per Chat Session.
- Every terminal contract carries Session, Agent, Runtime, and generation authority.
- Later phases may consume Phase 1 interfaces but cannot redefine them.

### Runner protocol

- Existing Runner Control stream carries bounded Terminal open/terminate intents only.
- One dedicated bidirectional gRPC RPC exists per active Terminal.
- Shared wire contracts remain OS-neutral and expose no POSIX implementation details.
- `terminal.v1` is the only initial capability identifier.

### Policy

- `terminal_enabled` is a first-class default-true field on infrastructure Profile, Workspace Profile, and Agent rows.
- Effective policy is server-authored and fail closed.
- Terminal-only Profile changes do not alter physical Runtime configuration or trigger recreation.
- `shell_enabled` remains present through Phase 3 and is completely removed in Phase 4.

### Browser protocol

- Terminal uses a dedicated ticket and WebSocket, not Chat WebSocket.
- Binary frame and typed control contracts are fixed by Design M2.
- Web consumes generated APIs and does not reconstruct Runtime or policy state.

### Runtime lifecycle

- No phase may add a Terminal lock, lease, or wait to Runtime stop/restart/reset/recreate/repair/removal.
- Every Terminal operation is fenced by current Runtime desired generation and Runner connection generation.

## Phase Dependencies and Owners

| Workstream | Primary owner | Reviewer | Dependency |
| --- | --- | --- | --- |
| Shared protobuf and runtime-control typed contracts | `/root/terminal-protocol-owner` | `/root/terminal-reviewer` | Approved Design |
| Runner PTY backend and Terminal registry | `/root/terminal-runner-owner` | `/root/terminal-reviewer` | Phase 1 protocol contract |
| Runtime Control Terminal gRPC integration | `/root` | `/root/terminal-reviewer` | Phase 1 protocol contract |
| Policy schema, migrations, repositories, services | Phase 2 owner assigned at phase start | `/root/terminal-reviewer` | Phase 1 |
| Terminal coordination, API, WebSocket | Phase 2 owner assigned at phase start | `/root/terminal-reviewer` | Phase 1 |
| Main Web Terminal and management UI | Phase 3 owner assigned at phase start | `/root/terminal-reviewer` | Phase 2 generated API |
| `shell_enabled` removal | Phase 4 owner assigned at phase start | `/root/terminal-reviewer` | Phase 3 |
| E2E, Specs, validation, cleanup | Phase 5 owner assigned at phase start | `/root/terminal-reviewer` | Phase 4 |

Owners edit only their assigned paths. Shared generated protobuf files belong to the protocol owner in Phase 1. Shared generated OpenAPI clients belong to the phase that changes the source API. The primary agent owns integration, branch progression, final validation, and PR creation.

## Data and Migration Work

- Phase 2 generates one Alembic revision adding the three `terminal_enabled` columns with non-null `true` defaults and updates the revision pointer.
- Phase 4 generates a later linear Alembic revision dropping `agents.shell_enabled` after active source stops reading it.
- Historical migrations are immutable.
- Migration tests cover upgrade, downgrade, existing-row defaults, and the intentional inability to restore historical Shell values after downgrade.

## API and Generated Clients

- Phase 1 regenerates Python protobuf and gRPC modules through the repository generator.
- Phase 2 dumps Public/Admin OpenAPI and regenerates affected Python/TypeScript clients for additive Terminal policy and API contracts.
- Phase 3 consumes only generated clients and adds xterm dependencies through pnpm lock resolution.
- Phase 4 removes `shell_enabled` from source schemas, dumps OpenAPI, and regenerates every affected client in the same PR.
- Generated files are never edited manually.

## Runtime and Operational Work

- Phase 1 proves PTY allocation, resize, Ctrl-C, byte ordering, stream retry, lifetime timers, quotas, and complete session cleanup.
- Phase 2 proves coordination parity, authorization, active revocation, Runtime-priority invalidation, and fail-closed mixed Runner versions.
- No live cluster mutation is required. Helm work is limited to chart documentation or values/tests if application heartbeat cannot provide a controller-neutral contract.

## Test and E2E Work

- Phase 1: deterministic unit and gRPC integration tests for shared protocol and Runner.
- Phase 2: repository/service/API/coordination parity tests and backend WebSocket integration tests.
- Phase 3: TypeScript unit/component/story tests and focused browser integration where practical.
- Phase 4: migration, resolver, Worker, API, generated-client, Web, seed, and static removal tests.
- Phase 5: required real-Docker Runtime protocol E2E and Web E2E matrix from Design M13.

No external credential or prerequisite snapshot is required. Product state is created only through Public/Admin APIs or UI. No direct database writes are allowed in feature E2E.

## Removal Obligations

| Obligation | Owning phase | Absence evidence |
| --- | --- | --- |
| Chat WebSocket remains free of Terminal frames | Phase 2 | Chat transport contract tests and static type inventory |
| Existing operation streams do not carry PTY bytes | Phase 2 | Coordination interface tests and protocol inventory |
| Pipe process abstraction is not reused as PTY | Phase 1 | Separate PTY interface/tests; existing process tests unchanged |
| `shell_enabled` active code/contracts/state removed | Phase 4 | schema, source, OpenAPI, generated client, Web, seed, and test inventory |
| Temporary visual-review harness and scope note removed | Phase 3 or 5 | Git absence and equivalent real stories |
| No durable Terminal content store | Every phase | schema/object-store/log capture tests |
| Current Living Specs no longer describe Shell gating | Phase 5 | `/spec-review` and bounded grep excluding historical docs/migrations |
| Feature plans removed after validated spec promotion | Phase 5 final checkpoint | Git absence |

## Spec Impact

Phase 5 updates at least:

- `docs/azents/spec/domain/agent.md`;
- `docs/azents/spec/domain/toolkit.md`;
- `docs/azents/spec/domain/workspace.md`;
- `docs/azents/spec/domain/conversation.md` when Session Terminal ownership is added;
- `docs/azents/spec/flow/agent-runtime-control.md`;
- `docs/azents/spec/flow/agent-runtime-persistence.md`;
- `docs/azents/spec/flow/test-strategy-e2e-primary.md`.

Run `/spec-review` once after implementation validation and before marking the snapshot implemented.

## Validation Matrix

| Scope | Commands/evidence |
| --- | --- |
| Runtime Control library | proto generator, Ruff, format, ty, pytest |
| Runtime Runner | Ruff, format, ty, pytest, PTY/gRPC focused tests |
| Azents backend | Ruff, format, ty, focused pytest, full affected suites, migration tests, OpenAPI drift |
| TypeScript | pnpm install, generate, format, lint, typecheck, build, component/story tests |
| Helm | lint and render tests when changed |
| E2E support | Ruff, format, ty, support tests |
| Required E2E | protocol and Web suites with Docker Runtime Provider |
| Removal | static inventory, schema inspection, generated-client absence, spec review |
| PR/CI | all five PRs created first, then required checks monitored with `gh` |

## Context Checkpoints

At every phase boundary record:

- completed approved mechanisms and Requirements;
- changed interfaces and generated surfaces;
- commands and evidence on the unchanged diff;
- removal obligations completed or remaining;
- scope-drift result in both directions;
- reviewer findings and applied corrections;
- next branch/base and rebase requirements;
- non-blocking risks and blockers.

A new product behavior or material mechanism returns to `feature-design`. Local implementation details remain in the owning phase plan.

## Rollout and Rollback

- Phase 1 and Phase 2 are additive and hidden/fail closed.
- Phase 3 exposes Terminal only for a current `terminal.v1` Runner and effective policy.
- Phase 4 is the destructive Shell-field cutover and includes its own migration rollback evidence.
- Phase 5 promotes Specs and implementation markers only after full validation.
- No compatibility fallback remains after Phase 4.
- No infrastructure resource is applied or restarted outside PR/CI execution.

## External Actions and Blockers

- External actions: create GitHub PRs and monitor CI only.
- Merge: prohibited without separate explicit requester approval.
- Current blockers: None.
- Design delta: `None`.

## Plan Cleanup

Keep this plan and phase plans through implementation, review, validation, and initial Phase 5 PR creation. After Phase 5 validation and Spec promotion are stable, remove all Terminal feature plan files in the final Phase 5 update and rerun invalidated checks.
