---
title: "session-260806 Phase 4 Frontend Execution Plan"
created: 2026-08-06
updated: 2026-08-06
tags: [session, privacy, frontend, plan]
---

# session-260806 Phase 4 Frontend Execution Plan

## Phase Execution Plan

- Phase: `4 — Frontend tabs + private draft`
- Branch/base: `feature/session-260806-user-sessions-04-frontend` → `feature/session-260806-user-sessions-03-owner-lifecycle`
- PR boundary: Team/My Sessions tabs, private draft admission wiring, separate list invalidation, locale strings
- Inputs: Phase 2 list/admission APIs + generated public client; Phase 3 lifecycle does not change UI contracts
- Deliverables:
  - Team / My Sessions tab control in Agent focused sidebar
  - Separate Team and My list queries with independent invalidation
  - My Sessions create opens private draft (`scope=user`) with no pre-create
  - First-message User admission via tRPC + navigation to concrete session route
  - en-US and ko-KR labels for tabs/empty/new copy
- Non-goals:
  - Full E2E matrix and living-spec promotion (Phase 5)
  - Owner lifecycle backend changes
  - Changing Team draft/create defaults
- Interfaces:
  - Team create/list remains default Team behavior
  - User draft does not call Team first-message APIs
  - No primary badge expectation for User Sessions
  - Associated User is not client-selectable
- Approved Design mechanisms: `M2` (UI), `M3` (draft UX)
- Authority references: `session-260806/REQ-1`, `REQ-2`; Design §§3–6,12
- Design delta: `None`
- Removal obligations:
  - Single undifferentiated Session list as the only Agent session projection in the focused shell
- Absence verification:
  - Team tab consumes Team list only; My tab consumes User list only
  - User draft first message uses User admission mutation

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| tRPC surface | `/root` | `typescript/apps/azents-web/src/trpc/routers/chat.ts` | Phase 2 client | list/create user session procedures | typecheck |
| Shell/sidebar | `/root` | `features/agents/components/AgentFocused{Shell,Sidebar}*` | tRPC | tabs + list wiring | story/typecheck |
| Draft container | `/root` | `features/agents/containers/useAgentDraftChatContainer.ts`, draft page route | tRPC | scope-aware admission | typecheck |
| Locales | `/root` | `messages/en-US.json`, `messages/ko-KR.json` | UI copy keys | localized labels | string presence |

- Integration order: tRPC → shell/sidebar tabs → draft scope → locales → checks → PR
- Independent review: `hardtack`; Team preservation, private draft non-create, separate invalidation
- Final validation: TypeScript format/lint/typecheck on web app as feasible
- Scope-drift check: no backend lifecycle/spec promotion
- Context checkpoint:
  - tRPC: `listAgentUserSessions`, `createUserAgentSessionMessage`
  - Shell dual-list queries + scope inference from draft `?scope=` and active session membership
  - Sidebar Team/My SegmentedControl; archived section Team-only
  - Draft admission branches on `sessionScope`; User draft uses User mutation only
  - Locales en/ko/ja/fr; stories MySessionsTab/Empty/TeamSessionsTab
  - Validation: pnpm format/lint/typecheck green

Design delta: `None`
