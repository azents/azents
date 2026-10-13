---
title: "Google Connection Phase 2 UI Execution Plan"
created: 2026-10-14
tags: [google, frontend, oauth, implementation, testing]
---

# Phase Execution Plan

- Phase: 2, localized management UI.
- Branch/base: `feature/google-261013-ui` → `design/google-261013-connection`.
- PR boundary: Google connection [2/3]: UI.
- Inputs: [Requirements](../requirements/google-261013-connection.md), [accepted ADR](../adr/google-261013-connection.md), [approved Design revision 4](../design/google-261013-connection.md), stable phase 1 generated API and successful phase 1 validation/review checkpoint.
- Deliverables: explicit task selection; same-context Connect/callback; truthful actual account and task-level partial/unknown review; fresh security acknowledgement and atomic save; recoverable uncertain publication; current saved status, ordinary reconnect and local disconnect; redacted public operator preparation and Admin direct configuration; localized accessible responsive components and substantive stories.
- Non-goals: new backend contracts, live consent/production configuration, token pooling, per-task/in-run consent, automated authorization/replay, Gmail send, generic MCP changes, permission inbox or paid scanner.
- Interfaces: consume generated public Google preparation/connect/exchange/review/confirm/reconnect-confirm/cancel/outcome/status/disconnect functions for both shared and exact Agent context. Admin consumes generated Google detail/PATCH with optimistic expected_version and explicit secret actions. No generated source is edited manually.
- Approved Design mechanisms: M11 and management/UI projections of M2–M5, M9, M13–M16; retained M6/M12 ownership and provider compatibility.
- Authority references: REQ-1, REQ-3–REQ-6, REQ-8–REQ-9; ADR-D1–D4 including accepted fresh-renewal clarification; current Toolkit/System Settings/Google Connection Specs; Main Web container/ADT/story/localization conventions.
- Design delta: None.
- Removal obligations: no existing provider removed. Route new Google creation only through candidate lifecycle, remove any new prototype/raw fetch path before completion; preserve generic metadata editing while ordinary reconnect remains authoritative for Google task permissions. No historical credential/state migration.
- Absence verification: no generic Google create bypass, persisted code/token/state plaintext, raw API fetch, automatic consent or arbitrary callback destination. Existing provider/Toolkit creation tests remain passing.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Typed API adapter and context | /root | Web tRPC Google router, shared Google schemas/resume helpers | Phase 1 contracts | Exact Agent/shared generated calls and validated nonsecret resume correlation | Schema/state tests, route semantic checks, typecheck |
| Progressive creation/review | /root | shared/toolkits Google container, pure components, ToolkitForm integration | Adapter/context | Select tasks, consent redirect, actual grant review, acknowledgement, publish/recovery | Colocated stories/play, partial/none/unknown/error/missing-preparation tests |
| Callback and saved lifecycle | /root | thin oauth/google callback route, feature callback container/component, shared saved Google container/components | Resume and typed lifecycle | Exact originating context, scrubbed transient URL, reconnect review, guarded local disconnect | Stale callback/context tests, outcome recovery, status/reconnect stories |
| Operator preparation | /root | Admin system-settings Google card/container/router | Phase 1 Admin contracts | Redacted current configuration, explicit secret replace/clear, version conflict feedback | Form/state tests, generated API typecheck and existing Admin regression |
| Localization and integration | /root | Web messages/composition, scoped Specs and phase checkpoints | Integrated UI | Aligned supported locales, responsive keyboard-operable states, preserved unrelated providers | Message tests, format/lint/types/build, component-story execution |

- Integration order: types/context/router; pure setup/review components and stories; root-owned container/Toolkit creation integration; callback and saved reconnect/disconnect; Admin preparation; locales/current Specs; integrated validation.
- Independent review: `/root/google-feature-reviewer`; read-only review of complete stable phase diff requested by root after all workstreams and root validation. Root applies findings directly and requests only material targeted re-review.
- Final validation: root-owned Web/Admin format/lint/typecheck/tests/build, substantive component stories and affected existing Toolkit tests; browser smoke/visual evidence with this Session's approved development environment when available. Full required provider/Web Google E2E belongs to phase 3 and is not replaced by stories.
- Scope-drift check: all new state/actions trace to approved mechanisms. No secret input in public UI; no task is silently preselected; granted evidence never inferred from requested scope; unknown/zero/missing renewal cannot be confirmed; cancellation does not promise remote reversal; no blind replay on uncertain outcome.
- Context checkpoint: phase 1 `cdefeda1ad0fd255d1171a5228126b3ca33025cb` / PR #2252 has independent review and latest CI 38448628646 success. Root integrated all UI workstreams without changing backend endpoints or credentials. Web 458 and Admin 49 tests passed; both type checks, lint, format checks and production builds passed. Eighteen real Storybook renders completed, including substantive play assertions, no horizontal overflow at 1280×1100 and 390×844, and a Korean mobile review. This is component evidence, not authenticated product/provider E2E. The same reviewer is requested on the stable integrated phase; final review/phase PR CI remain gates. Actual Google Preview/service interoperability and live authorization are unavailable/unapproved. Phase 3 final product E2E, same-SHA QA, spec promotion and plan cleanup remain.
