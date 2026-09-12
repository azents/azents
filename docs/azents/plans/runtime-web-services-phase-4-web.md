---
title: "Temporary Runtime Web Services Phase 4 — Main Web Experience"
created: 2026-09-12
tags: [runtime, web, implementation, planning, frontend, authentication]
---

# Phase Execution Plan

- Phase: `4/5 — Main Web experience`
- Branch/base: `feat/runtime-web-gateway-4-web` → `feat/runtime-web-gateway-3-gateway`
- PR boundary: Trusted Main Web confirmation and browser identity continuation, strict Runtime Web Chat request cards, and a coherent desktop/mobile Services panel.
- Inputs: Approved `web-260912` Requirements, ADR D1–D4 and D10, Design revision 2, and committed Phase 1–3 control/API/Gateway contracts.
- Deliverables: Production `__Host-` Main Web auth cookies with explicit local names; exact-origin unsafe control guard; shared-cookie issuance and separate-domain bind/ticket continuation pages; Runtime Web confirmation UI; strict known-tool Chat card; Services workspace panel tab with generated-client actions; aligned localization and pure stories/tests.
- Non-goals: New approval authority, OAuth event reuse, Runtime process controls, visibility/extend controls, broad browser compatibility, E2E infrastructure, Living Spec promotion and plan cleanup.
- Interfaces: Main Web calls only generated Runtime Web Public API contracts, performs all approval mutations on the trusted configured origin, sets browser cookies only in server routes, and projects the same endpoint/request/cycle state used by Chat and Services.
- Approved Design mechanisms: `M5, M6, M7, M8, M13, M14`.
- Authority references: `web-260912/REQ-2`–`REQ-4`, `REQ-6`, `REQ-9`, `REQ-10`, `REQ-12`, `REQ-13`; ADR-D1, ADR-D2, ADR-D3, ADR-D4, ADR-D10; approved Design revision 2.
- Design delta: `None`.
- Removal obligations: Replace production `az-token`, `az-refresh`, and `az-token-expires-at` cookies with `__Host-` names without dual-name fallback; do not map Runtime Web to OAuth AuthorizationRequestBubble; expose no visibility, extend, process-stop, authentication secret, or service-origin control mutation.
- Absence verification: Searches and tests prove old production cookie names do not authenticate, OAuth adapters remain unchanged, Runtime Web cards use strict tool metadata/current projection, generated clients own API calls, and Services actions contain no visibility/extend/process semantics.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Main Web auth and confirmation | root | `typescript/apps/azents-web/src/app/**`, auth/cookie/server API modules | Phase 3 auth API and Gateway broker | Host-only production auth cookies, exact-origin guard, shared/separate identity continuation and confirmation pages | server-route/cookie/origin unit tests and focused browser component tests |
| Runtime Web client integration | root | `typescript/apps/azents-web/src/features/runtime-web/**`, generated-client wrappers/tRPC | Generated Phase 3 client | Typed query/mutation hooks and current-state invalidation | TypeScript unit/type tests |
| Chat request card | root | Chat tool adapters and Runtime Web feature components | Phase 1 strict tool result metadata | Current-state card with approve/reject/cancel/copy/open actions and stale read-only behavior | adapter/container pure tests and stories |
| Services panel | root | workspace panel tabs, desktop panel, mobile Drawer, Runtime Web panel | Shared current projection | Empty/pending/active/active+pending/expired/disconnected/error/unconfigured states and direct actions | component tests, stories, responsive review |
| Localization | root | all supported locale Runtime Web namespaces | Final UI copy/state model | Aligned natural technical copy and accessible status/action labels | locale-key parity and TypeScript tests |

- Integration order: phase plan → production cookie and exact-origin server boundary → shared/separate auth continuation → generated-client Runtime Web feature layer → confirmation → Services panel → Chat adapter/card → localization/stories/tests.
- Direct implementation: root agent owns all implementation and integration. Delegation is limited to final read-only review.
- Independent review: `gateway-independent-reviewer` reviews trusted-origin/cookie secrecy, generated-client usage, no OAuth reuse, state/action coherence, stale handling, accessibility, desktop/mobile parity and Phase 4 scope.
- Final validation: focused TypeScript format/lint/type/tests/build for Main Web and public client; Storybook test/build where configured; pre-commit; stacked PR creation with Phase 3 base. Full CI remains deferred until Phase 5 PR exists.
- Scope-drift check: Every changed behavior must trace to M5–M8/M13/M14; reject new backend authority, Gateway transport changes, OAuth reuse, visibility/extend/process controls, unsupported browser mode, direct generated-file edits or Living Spec promotion.
- Context checkpoint: Phase completes when an authenticated user can establish either configured Gateway identity through trusted server routes, review and decide an exact pending request, and manage coherent service state from Chat and desktop/mobile Services UI without exposing control credentials to Runtime content.
