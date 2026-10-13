---
title: "Google Connection Phase 3 Integrated Verification Plan"
created: 2026-10-14
tags: [google, oauth, testing, implementation, security]
---

# Phase Execution Plan

- Phase: 3, deterministic assembled-product verification and Spec promotion.
- Branch/base: `feature/google-261013-verification` → `feature/google-261013-ui`.
- PR boundary: Google connection [3/3]: verification.
- Inputs: confirmed Requirements, accepted ADR and approved Design revision 4 M1–M16; phase 1 `cdefeda1a` PR #2252 reviewed/CI successful; phase 2 `68387f82f` PR #2253 reviewed/CI 38464284468 successful. Both remain unmerged.
- Deliverables: representative required API/Worker and browser Google connection flows with synthetic provider receipt/identity/MCP evidence; verified negative capability admission, atomic publication/replay and ordinary reconnect; current Specs, final integrated validation, immutable implementation snapshot and temporary-plan removal after verification.
- Non-goals: live Google accounts/resources, Preview certification, production/deployment/merge, new endpoint settings or test bypasses in product code, SDK verification disablement, token pooling, generic MCP redesign, blind replay or exhaustive branch duplication in E2E.
- Interfaces: official Google URLs and supported SDKs remain unchanged. An isolated E2E Docker network provides synthetic fixed-host TLS services and ephemeral CA trust only inside test containers. Seed and changes go through existing public/Admin APIs; no product DB writes. Main Web follows its actual Google callback and review paths. Worker uses existing deterministic model-response fixture support.
- Approved Design mechanisms: M1–M16; required representative boundary evidence plus narrow existing regression/race coverage.
- Authority references: Design Test Strategy and REQ-1–REQ-9; ADR-D1–D4; existing API/SDK/network ownership and testenv E2E-core-flow/fixture/data-write conventions.
- Design delta: None.
- Removal obligations: remove the multi-phase plan and all phase plans after final verification/Spec promotion. Preserve existing providers/data; no test-only product endpoint mode or prototype remains.
- Absence verification: search product/config/schema for provider bypass or endpoint mutation, verify generated clients unchanged, run affected existing provider suites and latest-SHA required/Web CI.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Synthetic Google prerequisite | /root | E2E support Google provider and fixture wiring | Supported SDK/fixed host contracts | Ephemeral TLS certificate/identity signatures; isolated authorization/code/nonce/scope/refresh/MCP state | Fixture decoder/certificate/transport tests, no external account/network dependence |
| Required product flow | /root | required/public Google connection tests, deterministic model-response fixture | Provider fixture and current API | API stage/review/confirm/replay, manager boundaries, Worker permitted/rejected tools, ordinary reconnect/cancel/disconnect | Real product image/API/Worker evidence; actual response assertions |
| Browser product flow | /root | web/public Google connection tests | Provider fixture and actual Main Web | Same-context shared/Agent setup, actual partial review, explicit acknowledgement/save, return restoration and reconnect metadata preservation | Real browser/navigation/API boundary; no copied auth state |
| Integrated QA and promotion | /root | related Specs, Requirements/Design implemented date, temporary plans | Stable implementation plus evidence | Same-SHA generated-client/docs/quality/CI result, accurate live limitations and plan cleanup | Root-owned validation and same independent reviewer |

- Integration order: typed synthetic prerequisite; required API flow and narrow provider transport checks; deterministic Worker tool flow; representative browser creation/reconnect; final quality/generated-client/spec review; snapshot promotion and plan cleanup.
- Independent review: `/root/google-feature-reviewer`, read-only review of the stable integrated final phase. Root applies all findings; targeted material re-review as required.
- Final validation: root runs relevant Python Ruff/format/ty, fixture support checks, required Google/API/Worker and Web E2E, affected frontend tests/build, OpenAPI/client synchronization and documentation checks. Latest-SHA CI runs the entire required/Web matrix as selected by current policy. Failures are recorded and fixed, not converted to skips. Optional live Google verification is explicitly conditional without approved prerequisites.
- Scope-drift check: fixed endpoints/signature/nonce verification and actual grant authority stay intact; fixture success never becomes live interoperability. Representative product tests complement 110 focused backend contracts, PostgreSQL races, 473 Web tests, 49 Admin tests and 18 real component renders.
- Context checkpoint: two prior phases reviewed, local checks and latest CI succeeded. Phase 2 initial Runtime Web restart/relay run failed with 503/owner-route conflict; corrected-head CI later passed without changing that runtime path. That earlier failure remains recorded, not proof of a Google regression or a comprehensive runtime fix. Live Google access remains unavailable/unapproved. Root remains sole implementer.
