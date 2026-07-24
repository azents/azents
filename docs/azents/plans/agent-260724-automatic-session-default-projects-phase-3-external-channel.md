---
title: "Automatic Session Default Projects Phase 3 External Channel"
created: 2026-07-24
tags: [agent, session, external-channel, backend, implementation]
---
# Automatic Session Default Projects — Phase 3 External Channel

## Phase Execution Plan

- Phase: `3 — External Channel integration`
- Branch/base: `feat/agent-default-projects-external-channel` → `feat/agent-default-projects-root-sessions`
- PR boundary: Route the two External Channel automatic root Session creation paths through the shared root creation service with Agent-default intent while preserving binding reuse, lock ordering, producer-owned transaction boundaries, activation ordering, and post-commit wake-up behavior.
- Inputs: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md), [`agent-260724/ADR`](../adr/agent-260724-automatic-session-default-projects.md), [`agent-260724/DESIGN`](../design/agent-260724-automatic-session-default-projects.md), the [multi-phase implementation plan](agent-260724-automatic-session-default-projects-implementation-plan.md), the [Phase 2 root Session plan](agent-260724-automatic-session-default-projects-phase-2-root-sessions.md), and the shared `RootAgentSessionCreationService` from `feat/agent-default-projects-root-sessions`.
- Deliverables:
  - Authorization Allow creates a new External Channel root Session through `RootAgentSessionCreationService.create_root_session(...)` with `AgentDefaultRootWorkspaceIntent` before creating its binding, grant, and decision.
  - The already-granted initial binding path creates a new External Channel root Session through the same Agent-default boundary before creating its binding.
  - Both new-binding paths persist the current ordered automatic Project policy as direct root context Project rows without Runtime I/O.
  - Empty automatic policies preserve existing empty-workspace behavior.
  - Existing active bindings return and reuse their established Session without reading or reapplying the current policy.
  - Session, root context Projects, binding, grant and decision where applicable, activation metadata, and related producer writes remain atomic in the caller-owned transaction; wake-up remains post-commit.
  - Focused regression coverage proves configured snapshots, empty policy behavior, existing-binding reuse, and rollback atomicity.
- Non-goals: Provider-specific Project configuration; Slack credential or provider behavior changes; External Channel schema or migration changes; policy persistence or management API changes; OpenAPI or generated-client changes; Agent Settings UI/tRPC; testenv/E2E fixture work; living-spec promotion; Runtime validation or I/O; team-primary or explicit Chat/Input behavior changes; subagent creation changes.
- Interfaces:
  - `ExternalChannelAccessService` and `ExternalChannelEventProcessorService` receive `RootAgentSessionCreationService` through constructor/FastAPI dependency injection while retaining `AgentSessionRepository` for existing wake-up state transitions.
  - Each new Session uses the existing `AgentSessionCreate` values, including `AgentSessionStartReason.EXTERNAL_CHANNEL`, and passes `AgentDefaultRootWorkspaceIntent()` explicitly. Automatic defaults are never merged with an explicit path selection.
  - `RootAgentSessionCreationService` receives the producer-owned `AsyncSession`, performs no commit and no Runtime I/O, and returns the created AgentSession plus Project snapshot provenance.
  - The authorization Allow path keeps its current route, active-binding, resource, and request lock/read order and commits only after Session/context Projects, binding, grant, decision, activation-related writes, and delete intent are complete.
  - `_create_granted_initial_binding` keeps resource locking and existing-active-binding lookup before Agent or policy access. If a binding exists, it returns immediately without invoking the root creation service.
  - Binding creation remains after root Session and Project snapshot creation; all wake-up and provider delivery behavior remains after the existing commit boundary.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| External Channel root Session integration and focused tests | `external-session-ingress (continued)` | `python/apps/azents/src/azents/services/external_channel/access.py`, `python/apps/azents/src/azents/services/external_channel/event_processor.py`, `python/apps/azents/src/azents/services/external_channel/event_processor_test.py` | Phase 2 root creation contracts and Phase 1 policy repository | Both direct creation paths migrated to explicit Agent-default intent; constructor/test wiring updated; snapshot, empty, reuse, and rollback tests | Focused External Channel pytest, Ruff, format, Pyright |
| Integration and accepted review fixes | Primary agent | Phase plan, shared integration points, final cross-workstream fixes | Implementation workstream complete | Contract audit, scope-drift remediation, accepted review fixes, final verification, commit and PR | Full backend Ruff/format/Pyright/pytest; `git diff --check`; non-goal audit |
| Independent review | `backend-readiness (continued)` | Read-only complete Phase 3 diff | Primary verification complete | Severity-ranked review of policy application, reuse-first behavior, transaction atomicity, lock/commit/wake ordering, DI, tests, and scope | Review report with exact evidence; no implementation edits |

- Integration order:
  1. Add the shared root creation service as an explicit injected dependency to both External Channel services and update all direct test construction.
  2. Replace the authorization Allow direct Session creation only in the no-binding/no-linked-session branch, preserving all preceding locks and all following binding/grant/decision work.
  3. Replace the already-granted initial-binding direct Session creation only after the resource lock and existing-binding early return, preserving binding creation and activation flow.
  4. Add focused database-backed coverage for ordered configured Project snapshots and empty policy behavior on both creation paths, existing-binding reuse without policy access, and rollback of Session/context Projects with related External Channel writes.
  5. The primary agent audits the diff, runs focused and full verification, assigns independent review, applies accepted findings, rebases on the latest Phase 2 branch before commit, reruns affected validation, and creates the stacked PR.
- Independent review: Review the complete branch against `feat/agent-default-projects-root-sessions`. Prioritize exact two-callsite scope, explicit Agent-default intent, reuse before policy read, unchanged lock ordering, no service-owned commit or Runtime I/O, root Projects before binding commit, rollback atomicity across Session/context Projects/binding/grant/decision, unchanged activation and post-commit wake-up behavior, required regression coverage, and absence of provider/UI/testenv/spec/API/generated-client drift.
- Final validation:
  - `cd python/apps/azents && uv run pytest -vv src/azents/services/external_channel/event_processor_test.py`
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - `cd python/apps/azents && uv run pytest -vv`
  - `git diff --check`
- Scope-drift check: Compare `git diff --name-status feat/agent-default-projects-root-sessions...HEAD` and the working tree against this plan. Confirm the diff is limited to this phase plan and the two External Channel services plus their focused backend tests, with no migrations, policy API, OpenAPI/generated clients, frontend/tRPC, testenv, living specs, Runtime-provider behavior, Chat/Input/team-primary behavior, provider credentials, or subagent changes.
