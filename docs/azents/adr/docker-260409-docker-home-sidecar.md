---
title: "DockerAgentHomeClient sandbox-daemon Sidecar Historical Decision Reconstruction"
created: 2026-04-09
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: docker-260409
historical_reconstruction: true
migration_source: "docs/azents/design/docker-agent-home-sidecar.md"
---

# DockerAgentHomeClient sandbox-daemon Sidecar Historical Decision Reconstruction

- Snapshot: `docker-260409`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/docker-agent-home-sidecar.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### docker-260409/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Decisions (Discussion #2410 Summary)

| # | Point | Decision | Rationale |
|---|---|---|---|
| P1 | Daemon executor backend | **Docker exec via `docker.sock`** | prod reproduction rate > implementation cost. symmetric with k8s "remote exec" model |
| P2 | Daemon placement | **Sidecar container** | separate `sandbox-daemon-{agent_id}` container, isolated from main. mirrors k8s Pod structure |
| P3 | Prod-parity vs Local-dev | **Prod-parity target, gaps explicit as Non-goals** | document docker-specific limits as boundaries for future contributors |
| P4 | Sharing mechanism | **absorbed into sidecar refactor** — parameterize bind mount list, testenv injects additional binds | add `extra_binds` API to `ensure_ready` as keyword-only |
| P5 | Scope + stack | **Full scope (7 PR stack)** | sidecar promoted to primary path → medium-size refactor |

### Explicit source section: Alternative B — Hybrid (Embedded + Sidecar factory option)

Support both modes with factory parameter. Choose when needed.

**Rejection reason**: implementation cost doubled. Up-front investment for unused feature → YAGNI.

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
