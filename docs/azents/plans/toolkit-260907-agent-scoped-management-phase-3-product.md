---
title: "Agent-Scoped Toolkit Management Phase 3 Product Plan"
created: 2026-09-07
updated: 2026-09-07
tags: [toolkit, agent, frontend, oauth, e2e, spec, plan]
---

# Agent-Scoped Toolkit Management Phase 3 Product Plan

## Phase Execution Plan

- Phase: `3/4 Product and validation`
- Branch/base: `toolkit-agent-scope-3-product` → `toolkit-agent-scope-2-backend`
- PR boundary: Deliver the approved saved-Agent Toolkit management experience,
  callback routing, localization, deterministic product E2E, Living Spec promotion, and
  implementation marking on top of the generated Phase 2 contracts.
- Inputs: Phase 1 PR #1711; Phase 2 PR #1712; confirmed `toolkit-260907/REQ`;
  accepted `toolkit-260907/ADR-D1` through `ADR-D4`; approved
  `toolkit-260907/DESIGN` revision `1`; Phase 2 Agent management, setup, OAuth, and
  generated-client contracts.
- Deliverables: requester-relative enhanced Agent Toolkit section; explicit Toolkit type
  and ownership choice; shared attach/detach and Agent-only create/edit/test/OAuth/
  enable-disable/delete actions; text readiness and ownership labels; current legacy
  shared attachment experience for users without management authority; Agent-aware MCP
  and GitHub callbacks; aligned English/Korean/Japanese/French copy; component stories;
  required Public API and browser E2E; Living Specs; matching implemented dates on
  Requirements and Design.
- Non-goals: initial Agent creation changes, Chat guidance, automatic attach/create,
  ownership conversion, new providers, Draft persistence, Session/user Toolkit modes,
  live provider credentials, plan cleanup, PR merge, or live infrastructure changes.
- Interfaces: use only generated `@azents/public-client` operations through tRPC; the
  Agent capability boolean selects enhanced versus legacy flow without revealing
  Toolkit state; enhanced state consumes `AgentToolkitManagementResponse`; shared cards
  detach only; Agent-only cards own edit/test/enable-disable/reconnect/delete; callbacks
  select Agent versus Workspace exchange from explicit query context; unsaved form state
  remains client-only.
- Approved Design mechanisms: `M5, M6, M7`
- Authority references: `toolkit-260907/REQ-1` through `REQ-10`;
  `toolkit-260907/ADR-D4`; `toolkit-260907/DESIGN` revision `1`; current Agent,
  Toolkit, MCP OAuth, and execution-loop Specs; generated-client, container/component,
  ADT-state, localization, accessibility, and no-direct-DB-write conventions.
- Design delta: `None`
- Removal obligations: replace the query-coupled enhanced-authority Agent Toolkit
  selector with the approved container/component management flow while retaining the
  same legacy selector for non-authorized users; replace Workspace-only callback routing
  for Agent-owned MCP/GitHub setup; promote current behavior into Living Specs.
- Absence verification: search enhanced UI for raw API URLs and Workspace-only mutations;
  prove non-admin rendering still uses only legacy shared attachment queries; prove
  unsaved cancellation creates no resource; verify no Agent-owned delete/update action
  is offered on shared cards and no shared object mutation is offered in Agent settings.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| tRPC Agent Toolkit contracts | root Agent | `typescript/apps/azents-web/src/trpc/routers/toolkit.ts` and router tests | Phase 2 generated client | Typed management, CRUD, tests, GitHub setup, MCP OAuth operations | Router/unit type tests and generated-client-only search |
| Management state and container | root Agent | Agent Toolkit feature `types.ts`, `containers/**`, Agent form integration | tRPC contracts and Agent capability | ADT for loading/error/ready/setup/edit/delete plus invalidation and recovery | Container tests and query invalidation assertions |
| Product components | root Agent | Agent Toolkit components and reusable Toolkit form fields | Management container | Ownership/readiness cards, type/ownership choice, Agent-only form, confirmations, responsive keyboard flow | Component tests, Storybook states, accessibility assertions |
| Provider setup reuse | root Agent | Toolkit provider field components and setup context | Agent tRPC setup operations | Agent-aware connection tests and GitHub setup without Workspace mutation fallback | MCP/GitHub focused tests and callback message tests |
| Callback routing | root Agent | MCP and GitHub callback App Router modules | Agent context query fields | Explicit Agent exchange/relay and fallback return to saved Agent Toolkit section | Server/client callback tests and browser popup flow |
| Localization | root Agent | `messages/{en-US,ko-KR,ja-JP,fr-FR}/workspace.json`, OAuth copy if needed | Final component copy | Structurally aligned natural Toolkit terminology and action/status text | Locale structure tests and review |
| Public API E2E | root Agent | `testenv/azents/e2e/src/tests/required/public/test_toolkit.py` | Phase 2 Python client | Owner/Admin CRUD, manager denial, isolation, shared compatibility, disable/delete/effective behavior where deterministic | Required credential-free API E2E |
| Browser E2E | root Agent | `testenv/azents/e2e/src/tests/web/public/test_agent_toolkits.py` and existing web fixtures | Product UI | Owner task walkthrough, legacy non-admin path, keyboard flow, narrow layout order | Browser E2E artifacts; no direct DB writes |
| Living Specs and snapshot | root Agent | Toolkit, Agent, MCP OAuth, execution-loop Specs; Requirements/Design frontmatter | Stable validation | Current ownership/effective/UI/OAuth behavior and matching `implemented: 2026-09-07` | `/spec-review`, docs snapshot/index validation |
| Independent review | `toolkit-260907-reviewer` | Read-only | Stable Phase 3 diff | Product/authority/callback/accessibility/E2E/spec/drift review | Severity-ordered findings and Design delta |

- Integration order: phase plan → generated tRPC operations → enhanced management ADT and
  container → reusable provider/form surface → ownership/readiness components → AgentForm
  capability switch → callback routing → localization/stories/tests → Public API E2E →
  browser E2E → spec review and Living Specs → snapshot implementation marking → full
  quality gates → independent review → corrections → final validation.
- Independent review: `toolkit-260907-reviewer` reviews the stable diff read-only against
  Requirements, ADR, Design revision `1`, Phase 2 API contracts, this phase plan,
  ownership-correct actions, non-admin non-disclosure, callback context, credential
  secrecy, accessible task order, deterministic E2E, Specs, removal absence, and scope
  drift.
- Final validation: azents-web tests, locale structure tests, format, lint, typecheck, and
  build; Storybook build or focused story tests; required Public Toolkit E2E; browser E2E
  for Agent settings including keyboard and narrow viewport; affected backend tests if
  callback contracts change; testenv Ruff/format/`ty`; `/spec-review`; docs snapshot and
  index validation; changed-file pre-commit; `git diff --check`.
- Scope-drift check: M5/M6/M7 coverage is required; no new provider, Draft, Chat behavior,
  initial Agent creation flow, automatic attachment, ownership conversion, live secret,
  Session/user mode, new backend authority, or plan cleanup may enter this phase.
- Context checkpoint: before PR creation record exact UI states/actions, tRPC and callback
  operations, locale/story/E2E evidence, current Specs and implemented dates, removal
  searches, review/corrections, residual risks, Phase 4-only cleanup, and
  `Design delta: None`.
