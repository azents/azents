---
title: "sandbox-daemon Sidecar Separation + kube API Exec Integration Historical Decision Reconstruction"
created: 2026-04-03
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: sandbox-260403
historical_reconstruction: true
migration_source: "docs/azents/design/sandbox-daemon-sidecar.md"
---

# sandbox-daemon Sidecar Separation + kube API Exec Integration Historical Decision Reconstruction

- Snapshot: `sandbox-260403`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/sandbox-daemon-sidecar.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### sandbox-260403/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Discussion Points and Decisions

Decisions from Discussion #2271:

| # | Discussion point | Decision | Rationale |
|---|-----------|------|------|
| 1 | executor execution model | kubernetes_asyncio stream exec | already used in codebase, no process overhead |
| 2 | sidecar container composition | build separate image | image separation is purpose of this work |
| 3 | file API path routing | direct shared volume access | target files are all under `/mnt/agent-data` |
| 4 | per-user isolation | out of scope | decided in existing discussion |
| 5 | communication path | keep existing HTTP, daemon calls kube exec | no `SandboxDaemonClient` change needed |
| 6 | migration strategy | 2-step transition | sidecar separation + exec transition together |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
