---
title: "Google Direct Workspace Tools Implementation Plan"
created: 2026-10-21
tags: [google, implementation, backend, frontend, security]
---

# Google Direct Workspace Tools Implementation Plan

## Authority and ownership

- Requirements: [google-261021/REQ](../requirements/google-261021-direct-workspace-tools.md), REQ-1 through REQ-10.
- Accepted decisions: [google-261021/ADR](../adr/google-261021-direct-workspace-tools.md), ADR-D1 through ADR-D4.
- Approved [Design revision 1](../design/google-261021-direct-workspace-tools.md): M1, M2, M3, M4, M5, M6, M7, M8, M9, M10, M11, M12, M13.
- Approval: requester, collaborative, 2026-10-21 KST, complete Design.
- Implementation, integration, validation and corrections: `/root`.
- Single independent reviewer: `/root/google-direct-reviewer`, read-only one-way review of every complete stable integrated phase diff. No implementation delegation.
- Design delta: None.

## Delivery boundaries

Use the title prefix `Google direct tools [n/4]:`. Each branch depends on the preceding branch; open each PR before starting the next. Intermediate phases are not deployable release boundaries. The only release boundary is the final drained cutover described in ADR-D4.

| Phase | Branch/base | Deliverable and authority | Integration boundary |
| --- | --- | --- | --- |
| 1 Foundation | `feat/google-direct-foundation` / `main` | Canonical service/request/grant contracts, complete operation-scope catalog, deterministic old-shape transformation and preflight tests (M1/M2/M4/M5/M9/M10/M13) | Pure contracts and migration primitives; no activation of new persisted shape while existing consumers still require tasks |
| 2 Direct execution | `feat/google-direct-execution` / phase 1 | Typed official SDK tools, current admission/refresh fences, Gmail/Calendar/Drive families, canonical files and bounded transport (M1/M2/M3/M5/M7/M8/M10/M13) | Replace Google MCP/scanner execution, update internal consumers and focused tests; do not add an old/new decoder |
| 3 Management and cutover | `feat/google-direct-management` / phase 2 | Service updates, staged OAuth, minimal Picker issuance/UI, operator preparation, generated clients, complete one-time migration (M3/M4/M5/M6/M8/M9/M11/M12/M13) | Atomically activate new management/config contract, remove task/ack DTOs and UI, wire Phase 1 transformations into generated Alembic migration after consumers are replaced |
| 4 Integrated verification | `feat/google-direct-verification` / phase 3 | Assembled provider/browser E2E, remaining race/format tests, specs and cleanup (M1-M13) | Full direct-provider product evidence, validated spec promotion and removal of these temporary plans |

The cutover migration is intentionally activated with the replacement management consumers, not in the foundational primitive PR. This is execution ordering within the approved single stopped cutover, not a compatibility mode. No intermediate phase may be deployed.

## Interfaces and removal ownership

- Phase 1 separates actual-scope operation projection from supported OAuth request intent. Enabled services are independent of requested scope bundles. Unknown/empty grants admit nothing. Mixed Drive grants retain whole-read/app-file-write distinctions.
- Phase 2 consumes typed catalog operations, current execution owner and exact-current grant/client/config state. Requests contain access-only credentials and no implicit refresh/retry. Each compound step independently admits authority.
- Phase 3 reuses current shared/Agent/personal manager context, staged callback and atomic publication. Local service saves use existing Toolkit revision. Picker token delivery is manager-bound, short-lived and strictly minimal; unexpected rotation preserves renewal exactly-current, marks reconnect-required and returns no browser token.
- File authority stays in canonical Exchange/Artifact/current-run VFS/Runner transfer services. No Worker-local interpretation of Runtime paths.
- Remove task ceilings and obsolete policy when consumers switch in phases 2/3. Remove Google MCP endpoints/discovery/snapshots, scanner/binary rejection and scanner-only tests with phase 2 execution replacement. Remove task/ack config/DTO/UI and preparation claims with phase 3. Replace Google-only MCP fixtures in phase 4; generic MCP, Analytics and generic file services remain.
- Migration preserves published IDs, owner/delegation, encrypted current grants and historical outcome identity; invalidates and scrubs incomplete attempts; removes only precisely attributable Google snapshot/deferred state. Malformed or ambiguous data aborts atomically. No decryption or external I/O in a DB transaction.
- Absence checks search production Google code, fixtures, DTOs, generated contracts and UI references, excluding immutable historical documents. Positive direct-operation tests replace obsolete tests, rather than adding removal-only tests.

## Validation and prerequisites

Root runs focused Ruff, type checking and pytest per phase, then affected complete-subproject checks. Phase 1 tests complete scope alternatives and old/new transform invariants. Phase 2 tests actual public SDK routing, single-request/zero-refresh retry behavior, compound partial results, MIME/calendar/query validation and bounded file handling. Phase 3 tests manager/callback/publication/service/refresh/Picker races, isolated migration from the previous schema, client regeneration, component tests and Web/Admin checks. Phase 4 owns assembled API/Worker/PostgreSQL direct-provider E2E and browser-boundary flows.

Use synthetic fixed-host OAuth/identity and REST/SDK provider fixtures with ephemeral TLS/client references, two accounts/clients, all ownership variants, partial/unknown/empty/broad grants, app-file/whole-read mixed permissions, deterministic barriers and measured provider effects. Never record token values, mail/file content or capability URLs in evidence. Record exact commands, SHA, environment, exit status, migration invariants and file size/hash results.

Live Google interoperability, strict minimal Picker token issuance/selection, account feature eligibility, format fidelity and policy/compliance remain separately conditional. No credentials, app review or authorization are available for live checks; report the explicit prerequisite gap rather than claiming a live pass. Do not weaken CI duration gates or required coverage. Generate public/admin OpenAPI and Python/TypeScript clients from source contracts, never by hand.

## Rollout, checkpoints and cleanup

Merge, deployment, production checkpoint/migration and live authentication/effects are not authorized. A future authorized operator must stop admission/old writers, verify quiescence and checkpoint, run transactional preflight/cutover, verify invariants and only then admit new work. Image-only rollback is insufficient and remote effects are not reversible by restore.

At each phase record PR/base/SHA, completed behavior, changed interfaces, validation, exact reviewer findings/corrections, removal evidence, remaining work and risks. Freeze the integrated diff before requesting the same reviewer. Material product/mechanism drift returns to Requirements/technical design; local execution details stay root-owned. Promote current Specs only to verified implemented behavior; mark Requirements/Design implemented together after full validation. Remove all feature plans after promotion, without creating an otherwise unnecessary cleanup PR.

## Current checkpoint

Foundation branch starts at `cc1d82fa9` (current main at start). Design approval recorded; no implementation activated, no migration generated or executed, no remote provider calls. Phase 1 execution contract follows in its companion plan.
