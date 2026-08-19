---
title: "Session Model Change Phase 3 Composer Server Profile Plan"
created: 2026-08-19
tags: [model, session, frontend, composer, chat]
---

# Model 260819 Session Model Change — Phase 3 Composer Server Profile

## Phase Execution Plan

- Phase: `3 — Composer server-owned profile and frontend removal`
- Branch/base: `feature/model-260819-3-composer-server-profile` → `feature/model-260819-2-admission-turn-boundaries`
- PR boundary: Frontend Composer behavior, model-profile PUT integration, authoritative Session cache convergence, and removal of browser/local profile authority.
- Inputs: Phase 1 Session applied-intent/API/generated-client foundation; Phase 2 admission and fresh-turn boundary behavior; approved Requirements, ADR, and Design revision 2.
- Deliverables: Composer initializes from nullable applied Session intent plus effective Agent baseline; picker changes remain local; model-only Apply calls idempotent PUT; explicit Send/edit/TurnAction profile behavior remains intact; Stop and Apply coexist; text/action-only drafts persist; local profile relay and browser profile persistence are absent; focused TypeScript tests/stories pass.
- Non-goals: Backend/API implementation, worker behavior, E2E fixture work, Living Spec promotion, plan cleanup, live infrastructure changes, PR creation, or merge.
- Interfaces: Generated public-client model-profile PUT; stable `AgentSessionResponse.current_model_target_label/current_reasoning_effort` projection of applied intent; existing `ChatWriteResponse` explicit-profile response; tRPC `chat` router and Session query invalidation; `ChatInput` pending profile and Apply callback.
- Approved Design mechanisms: M7, M8, M10, M11; integrates with M1, M3, and M4 interfaces.
- Authority references: `model-260819/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, `REQ-5`, `REQ-8`, `REQ-9`; `model-260819/ADR-D1`, `ADR-D2`, `ADR-D4`; Design revision 2 mechanisms M7, M8, M10, M11; Conversation and Agent Execution Loop Living Specs.
- Design delta: `None`
- Removal obligations: Remove `latestHumanInferenceProfile`, `composerInferenceProfileState`, ChatView/ChatSessionView profile relay props, pending-profile subscription authority, `azents.chat.lastSelectedInferenceProfile.*` reads/writes/cleanup, draft `inference_profile` serialization/restoration, and profile-only parser/test/story setup. Retain text/action draft persistence and durable event/profile provenance display.
- Absence verification: Source search finds no removed concrete-session relay/state/key/parser references; Storybook and focused tests prove drafts contain only message/action, reload does not restore pending profiles, and header subscription selection derives only from authoritative server/effective profile inputs.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Composer state and action behavior | `model-260819-frontend-owner` | `typescript/apps/azents-web/src/features/chat/components/ChatInput.tsx`, `ChatInput.stories.tsx`, colocated profile/draft tests | Phase 1 response contract; existing visual mock | Local pending picker, effective baseline, model-only Apply, file/action/command rules, Stop coexistence, V2 visuals, text/action-only draft persistence | Focused Storybook/unit tests; source absence grep |
| Session container and view authority | `model-260819-frontend-owner` | `useChatSessionContainer.ts`, `ChatView.tsx`, `ChatSessionView.tsx`, related chat types | Phase 1 Session projection; tRPC mutation | Nullable applied profile output, effective baseline, no local applied relay, server-only subscription presentation | Typecheck; focused tests; source absence grep |
| Public-client/tRPC integration | `model-260819-frontend-owner` | `src/trpc/routers/chat.ts`, generated-client call integration only where generated output is refreshed by Phase 1 | Phase 1 OpenAPI/generated client | Idempotent model-profile PUT mutation and Session query invalidation after mutation/explicit writes | Typecheck/lint; generated API contract compile |
| Regression stories/tests | `model-260819-frontend-owner` | ChatInput/ChatView stories and focused chat tests | Composer and container workstreams | Null baseline, pending/revert, model-only Apply, Stop+Apply, draft removal coverage | Storybook test runner or focused test command |

- Integration order: (1) confirm Phase 1 generated PUT operation and response type; (2) add tRPC mutation and cache invalidation; (3) refactor container output and ChatSessionView/ChatView source-of-truth; (4) refactor ChatInput persistence and submission controls; (5) update stories/tests; (6) run focused formatting/lint/typecheck/build/tests; (7) request exact reviewer and apply blocking findings.
- Independent review: `/root/model-260819-implementation-reviewer`, read-only. Review the Phase 3 diff against Requirements/ADR/Design rev2 and this plan. Criteria: M7/M8/M10/M11 complete; no unauthorized source of truth, compatibility reader, fallback, or layout redesign; model-only PUT has correct idempotency/client key and cache invalidation; explicit input paths preserve profile semantics; Stop remains available; removal obligations have source/test absence evidence. Output: blocking/non-blocking findings and explicit approve/request-changes verdict.
- Final validation: `pnpm run format --filter=@azents/web` (or repository-equivalent), `pnpm run lint --filter=@azents/web`, `pnpm run typecheck --filter=@azents/web`, `pnpm run build --filter=@azents/web`, focused Storybook/unit tests for chat, source searches for removed keys/relays, and `git diff --check`.
- Scope-drift check: Approved coverage is limited to frontend/public-client integration, Composer behavior, cache convergence, relevant stories/tests, and this phase plan. Unauthorized additions include backend/worker changes, E2E/Living Specs, plan cleanup, new user-visible contracts beyond approved PUT integration, new persistence/fallback/authority, or layout relocation. Any material behavior not in M7/M8/M10/M11 returns to feature design; `Design delta` remains `None`.
- Context checkpoint: Starting from Phase 2 HEAD `3d5eba3fa`; pre-existing uncommitted visual Composer changes are retained and audited. Remaining scope after this phase is Phase 4 E2E, Living Spec updates, implementation metadata/plan cleanup, and final stack integration. Risks: generated client operation availability, stale Session query convergence after idempotent replay, preserving pending local state across unrelated rerenders, and Stop/Apply action eligibility.
