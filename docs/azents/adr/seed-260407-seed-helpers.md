---
title: "Full-stack Local Test Environment — Stage 1c (Test Data Seed Helpers) Historical Decision Reconstruction"
created: 2026-04-07
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: seed-260407
historical_reconstruction: true
migration_source: "docs/azents/design/seed-helpers.md"
---

# Full-stack Local Test Environment — Stage 1c (Test Data Seed Helpers) Historical Decision Reconstruction

- Snapshot: `seed-260407`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/seed-helpers.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### seed-260407/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decision Summary

Detailed rationale in Discussion #2358 §3.

| # | Decision | One-line summary |
|---|---|---|
| 1 | shape | `import`-able library (not CLI). Pass objects through function return values |
| 2 | isolation | default is `unique()` pattern; use `devserver down --all && up` if clean DB needed |
| 3 | e2e utils reuse | **Option B (own code)** — separate due to dependency direction and granularity philosophy |
| 4 | granularity | one function = one domain object, dependencies as explicit args |
| 5 | LLM key | default `"sk-test-dummy"`; caller explicitly passes real key |
| 6 | module layout | `testenv/nointern/seed/{auth,workspace,agent,llm}.py` + internal helpers `_client/_types/_unique` |
| 7 | Admin auth | internal network assumption, admin client used without token (feasibility needed) |

Discarded items: CLI structure / output-storage style / preflight integration (Discussion #2358 §5).

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
