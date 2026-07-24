---
title: "Automatic Session Default Projects Phase 2 Root Sessions"
created: 2026-07-24
tags: [agent, session, backend, implementation]
---
# Automatic Session Default Projects — Phase 2 Root Sessions

## Phase Execution Plan

- Phase: `2 — Shared root Session initialization and team-primary`
- Branch/base: `feat/agent-default-projects-root-sessions` → `feat/agent-default-projects-policy`
- PR boundary: Introduce the shared root AgentSession creation boundary, migrate explicit non-primary producers, and apply Agent-default Project snapshots only when a new team-primary Session wins creation.
- Inputs: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md), [`agent-260724/ADR`](../adr/agent-260724-automatic-session-default-projects.md), [`agent-260724/DESIGN`](../design/agent-260724-automatic-session-default-projects.md), the [multi-phase implementation plan](agent-260724-automatic-session-default-projects-implementation-plan.md), and Phase 1 policy persistence/API from `feat/agent-default-projects-policy`.
- Deliverables:
  - A closed root workspace intent union that keeps an explicit empty Project list distinct from Agent-default intent.
  - A `RootAgentSessionCreationService` that accepts the producer-owned `AsyncSession`, never commits it, and creates the root AgentSession, root SessionAgentContext, and initial context Project rows in that transaction.
  - A structured creation result containing the AgentSession, whether the underlying team-primary row was newly created when applicable, resolved initial Project paths, and the applied policy revision for a newly created Agent-default root context.
  - A team-primary repository ensure result that distinguishes a race-winning insert from an existing/reused primary.
  - Migration of Chat and buffered-input explicit non-primary root creation to the shared boundary without changing setup-action ordering or preset, catalog, and recency-default projections.
  - Team-primary creation through the shared boundary so only the race winner applies the current policy snapshot and a reused primary remains unchanged.
- Non-goals: External Channel producer migration; Agent Settings UI or tRPC; Runtime validation or I/O during Session creation; Project-count limits; Git worktree provisioning changes; subagent creation changes; living-spec promotion; compatibility wrappers for the old team-primary repository return type.
- Interfaces:
  - `ExplicitRootWorkspaceIntent(existing_project_paths)` and `AgentDefaultRootWorkspaceIntent()` form the closed service-layer input union.
  - `RootAgentSessionCreationService.create_root_session(session, create, workspace_intent)` creates a non-racing root Session. Explicit paths are normalized and de-duplicated; Agent-default paths come from one coherent policy snapshot.
  - `RootAgentSessionCreationService.ensure_team_primary(session, workspace_id, agent_id)` owns automatic team-primary initialization and returns the same structured result.
  - `AgentSessionRepository.ensure_team_primary_for_agent(...)` returns `{session, created}`. It remains the unique-constraint race boundary but does not read or apply the Agent policy.
  - On a newly created Agent-default root context, context Project rows are the durable snapshot and `policy_revision` is result/log provenance only. No SessionAgentContext schema change is introduced.
  - On a reused team-primary, the service returns its existing context Project paths with `created=false` and `policy_revision=None`; it never rereads or reapplies the current policy to that context.
  - Explicit producers retain their existing selection side effects in the same producer transaction after the shared boundary creates direct context Projects. Explicit empty paths remain empty and never merge with Agent defaults.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Root Session creation and producer migration | `policy-management-impl (continued)` | `python/apps/azents/src/azents/services/root_agent_session_creation/**`, `python/apps/azents/src/azents/repos/agent_session/{__init__.py,data.py,repository_test.py}`, `python/apps/azents/src/azents/services/chat/**`, `python/apps/azents/src/azents/services/agent_session_input.py`, related backend tests and test fixtures requiring the new ensure result | Phase 1 policy repository and existing SessionAgentContext/Project repositories | Closed intent/result contracts, shared creation service, repository race result, Chat/Input migration, focused tests | Focused repository/service/producer tests, Ruff, format, Pyright, relevant pytest suites |
| Integration and accepted review fixes | Primary agent | Phase plan, shared integration points, final cross-workstream fixes | Implementation workstream complete | Scope audit, accepted finding remediation, final validation, commit and PR | Full backend Ruff/format/Pyright/pytest; `git diff --check`; non-goal grep/audit |
| Independent review | `backend-readiness (continued)` | Read-only full Phase 2 diff | Primary verification complete | Severity-ranked review of correctness, atomicity, race behavior, side-effect preservation, context inheritance, and scope | Review report with exact evidence; no implementation edits |

- Integration order:
  1. Change the team-primary repository return contract and update direct callers/tests so created versus reused is explicit.
  2. Add the closed workspace intent/result models and shared root creation service using the Phase 1 policy repository and existing context Project repository.
  3. Migrate Chat and buffered-input explicit root creation and every team-primary producer to the shared service while preserving producer-owned side effects and commit boundaries.
  4. Add atomic rollback, explicit precedence, automatic snapshot, reuse/race, no-side-effect, and subagent-inheritance coverage.
  5. The primary agent audits the complete diff, runs full verification, assigns independent review, applies accepted findings, and requests re-review.
- Independent review: Review the complete branch against `feat/agent-default-projects-policy`. Prioritize explicit/default intent separation, transaction ownership, coherent policy snapshots, team-primary winner/loser behavior, rollback of Session/context/Projects, unchanged explicit setup-action and recency behavior, no Runtime I/O, subagent context inheritance, and absence of External Channel/UI/spec scope drift.
- Final validation:
  - `cd python/apps/azents && uv run ruff check .`
  - `cd python/apps/azents && uv run ruff format --check .`
  - `cd python/apps/azents && uv run pyright .`
  - `cd python/apps/azents && uv run pytest -vv`
  - `git diff --check`
- Scope-drift check: Compare `git diff --name-status feat/agent-default-projects-policy...HEAD` and the working tree against this plan. Confirm there are no External Channel, frontend/tRPC, testenv, living-spec, Runtime-I/O, Project policy management API, migration, or generated-client changes in this phase.
