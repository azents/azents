---
title: "Automatic Session Default Projects Phase 4 Agent Settings Web"
created: 2026-07-24
tags: [agent, projects, frontend, testenv, e2e, implementation]
---
# Automatic Session Default Projects — Phase 4 Agent Settings Web

## Phase Execution Plan

- Phase: `4 — Agent Settings UI and deterministic E2E coverage`
- Branch/base: `feat/agent-default-projects-web` → `feat/agent-default-projects-external-channel`
- PR boundary: Add the AgentAdmin operational settings surface for automatic-Session default Projects, backed by generated Public API clients and deterministic browser/API E2E coverage, while extracting the existing Runtime directory picker into a neutral reusable feature boundary.
- Inputs: [`agent-260724/REQ`](../requirements/agent-260724-automatic-session-default-projects.md), [`agent-260724/ADR`](../adr/agent-260724-automatic-session-default-projects.md), [`agent-260724/DESIGN`](../design/agent-260724-automatic-session-default-projects.md), the [multi-phase implementation plan](agent-260724-automatic-session-default-projects-implementation-plan.md), and completed policy/API, root Session, and External Channel phases through `feat/agent-default-projects-external-channel`.
- Deliverables:
  - An Agent Settings hub row labeled `Default projects`, showing configured count or `None`, linking to `/w/{handle}/agents/{agentId}/settings/projects`.
  - Generated-client-backed Agent tRPC query and complete-replacement mutation for the automatic Session Project policy.
  - Stable structured Public API error detail exposed in tRPC client error data so revision conflict, Runtime unavailable, and invalid-path recovery do not depend on parsing messages.
  - A neutral Agent Workspace directory picker feature extracted from the chat-owned component/state contract and reused by existing Chat/new-Session consumers and the settings editor without duplicated Runtime query logic or reverse app/feature dependencies.
  - A container ADT and pure settings UI for loading, empty, clean, dirty, saving, Runtime unavailable, missing configured path, validation error, revision conflict, and generic error states.
  - Existing-directory-only add, remove, move up/down, save, retry, start-Runtime, and reload-latest behavior. No worktree/Git controls are exposed.
  - Project rows display basename, normalized full path, and informational Project Browser preview status while path remains policy identity.
  - Successful replacement invalidates policy and preview queries; failed saves retain the complete local draft. Revision conflict never overwrites automatically.
  - Localized copy for all supported locales, pure component stories for meaningful desktop/mobile states, and focused container/state tests.
  - Deterministic fixture support and E2E scenarios covering policy configuration, automatic/explicit snapshot behavior, missing path, Runtime unavailable clear/save behavior, revision conflict, and subagent inheritance through product/Public API and Runtime boundaries only.
- Non-goals: Worktree or Git-ref controls; provider/channel/participant-specific policy; automatic conflict overwrite; direct generated-client edits; product-table mutation from fixtures; live Slack credentials; living-spec promotion; validation report/evidence promotion; new product schema or backend policy semantics.
- Interfaces:
  - Agent tRPC query input is `{handle, agentId}` and returns the generated `AutomaticSessionProjectsResponse`; replacement input is `{handle, agentId, expectedRevision, projectPaths}` and calls `agentV1ReplaceAutomaticSessionProjects` with ordered paths.
  - `ApiError` remains the server-side source for HTTP status/body. tRPC error formatting exposes a bounded structured `apiError` projection containing stable `code`, user-visible `message`, and failing `path` when present; unrelated error bodies are not exposed wholesale.
  - The settings container owns query/mutation/preview/Runtime dependencies and converts them into a closed discriminated UI state. The pure component receives state and callbacks only.
  - The neutral directory picker owns reusable picker state/types/UI and Runtime workspace navigation actions. It accepts `existing directories only`; settings never receives worktree mode or Git-ref state.
  - Draft identity and dirty comparison use ordered normalized paths. Duplicate selected paths are ignored without changing the first occurrence.
  - A successful mutation adopts the returned revision/paths, clears dirty/conflict state, and invalidates the Agent policy and Project Browser preview queries. A failure preserves the draft.
  - Runtime-unavailable non-empty save offers Runtime start/retry; an empty clear remains saveable without Runtime. A revision conflict offers explicit `Reload latest` and retains local edits until chosen.
  - E2E setup creates/removes directories through the Runtime/runner test boundary, configures policy through the Public API or real Web UI, and verifies resulting Session Projects through Public APIs. Fixtures never write policy or Session Project tables directly.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Agent Settings frontend, neutral picker, tRPC/error projection, stories, and focused tests | `automatic-projects-frontend-feasibility (continued as implementation owner)` | `typescript/apps/azents-web/src/app/**/agents/[agentId]/settings/**`, `typescript/apps/azents-web/src/features/agents/**`, new `typescript/apps/azents-web/src/features/agent-workspace/**`, directly affected Chat workspace/new-Session picker consumers, `typescript/apps/azents-web/src/trpc/{api-error.ts,init.ts,routers/agent.ts}` and focused tests, `typescript/apps/azents-web/messages/*.json` | Generated Public client from Phase 1 and existing workspace/project-preview tRPC boundaries | Complete settings route/hub/editor, neutral picker reuse, stable error projection, localized stories/tests | TypeScript format, lint, typecheck, build, focused tests/Storybook build as available |
| Deterministic fixture and product E2E scenarios | `validation-readiness (continued)` | `testenv/azents/e2e/src/tests/azents/public/**` automatic-project policy/browser scenario files, narrowly required `testenv/azents/e2e/src/support/**` fixture helpers, and focused testenv fixture tests | Fixed tRPC/picker route labels and existing Phase 1-3 Public APIs | Runtime-backed directories, disposable missing-path operation, real settings Web journey, API assertions for automatic/explicit/snapshot/conflict/subagent matrix | Focused testenv Ruff/format/Pyright/pytest and selected deterministic Web/API E2E commands |
| Integration and accepted review fixes | Primary agent | Phase plan, shared interface resolution, final cross-workstream fixes | Both implementation workstreams complete | Scope audit, integration, accepted finding fixes, final validation, commit and PR | Full TypeScript and testenv quality/build/E2E checks; backend checks if shared error code changes require them; `git diff --check` |
| Independent review | `frontend-readiness (continued)` | Read-only complete Phase 4 diff | Primary verification complete | Severity-ranked review of UX state completeness, architecture, error recovery, generated-client usage, picker ownership, E2E integrity, localization, accessibility, responsive behavior, and scope | Review report with exact evidence; no implementation edits |

- Integration order:
  1. Fix the shared contracts first: Agent tRPC policy procedures, bounded tRPC API error projection, and neutral directory picker state/UI boundary.
  2. Migrate existing Chat/new-Session picker consumers to the neutral boundary without changing their explicit workspace behavior.
  3. Build the Agent Settings route, hub count row, container ADT, pure component, localization, stories, and focused tests on the fixed contracts.
  4. In parallel after route labels/API contracts are stable, add Runtime-backed fixture support and deterministic API/browser scenarios without direct product-table writes.
  5. The primary agent integrates both workstreams, audits draft/conflict/error transitions and mobile accessibility, runs full validation, assigns independent review, applies accepted findings, rebases on the latest Phase 3 branch before commit, reruns affected checks, and creates the stacked PR.
- Independent review: Review the complete branch against `feat/agent-default-projects-external-channel`. Prioritize AgentAdmin-only access assumptions, generated-client use, bounded stable error data, complete ADT states and draft preservation, optimistic-conflict recovery, empty-clear behavior without Runtime, picker extraction ownership and unchanged Chat behavior, no Git/worktree controls, query invalidation, Project preview/missing status, localized utility copy, keyboard/focus/mobile behavior, E2E use of product/Runtime boundaries, and absence of generated-client/backend schema/spec/provider scope drift.
- Final validation:
  - `cd typescript && pnpm run format`
  - `cd typescript && pnpm run lint`
  - `cd typescript && pnpm run typecheck`
  - `cd typescript && pnpm run build`
  - focused azents-web component/container tests and Storybook build when configured
  - `cd testenv/azents/e2e && uv run ruff check .`
  - `cd testenv/azents/e2e && uv run ruff format --check .`
  - `cd testenv/azents/e2e && uv run pyright .`
  - focused deterministic API and browser E2E scenarios for automatic Session Projects
  - `git diff --check`
- Scope-drift check: Compare `git diff --name-status feat/agent-default-projects-external-channel...HEAD` and the working tree against this plan. Confirm there are no generated-client edits, backend policy/Session/External Channel semantic changes, migrations, provider credentials, live-provider tests, worktree/Git controls, living-spec promotion, or PR 7 validation-report work.
