---
title: "Lag-Tolerant Catalog and Memory Projection Requirements"
created: 2026-10-04
tags: [backend, concurrency, memory, model-catalog]
document_role: primary
document_type: requirements
snapshot_id: readmodel-261004
---

# Lag-Tolerant Catalog and Memory Projection Requirements

## Primary System Outcome

Catalog and historical Memory descriptions tolerate committed lag and disappeared references without acquiring explicit read/ancestor locks merely to enforce the newest globally coherent view. Authorization, immutable artifact identity and critical mutation acceptance remain correct.

## Confirmed Scope

This is the catalog/Memory phase of the requester-confirmed lag-tolerant read and defensive-lock removal sequence, which the requester directed the Agent to continue after the session-capability foundation. It preserves the existing public model-support and Memory privacy contracts; it introduces no new approval workflow, cache authority or product policy.

## Requirements

### REQ-1 — Catalog descriptions are nonblocking

Current catalog picker, exact local model descriptions, optional context maxima, source metadata and maintenance projections perform ordinary scoped reads without explicit integration/source/catalog read locks. Publication interleaves may yield committed older or unavailable descriptions, but must not create false cross-query freshness/counter errors. Exact Workspace/provider/integration/model identity and optional source enrichment semantics remain intact.

### REQ-2 — Captured model acceptance remains exact

New model operations/profile acceptance continue to validate the exact consumed local value/absence inputs at the real persisted mutation boundary. Retries, takeover and history use existing captured candidates. Saved selection prices are not recaptured from current catalog metadata. No runtime structured-output downgrade, source fallback or visibility relaxation is introduced.

### REQ-3 — Memory uses the selected artifact's own authority

Historical foreground and live VFS reads use the exact existing immutable unit/revision and its complete dependency manifest. Ordinary turns retain authorized selected bytes rather than adopting a replacement current document. Missing/deleted/collected references are unavailable outcomes, not cross-query freshness corruption. Artifact byte validation remains mandatory.

### REQ-4 — Privacy denial and producer publication stay enforced

Exact Agent/Workspace/durable associated User, membership grant continuity, memory enablement, source archive/purge and availability-generation denial remain enforced by existing model/tool admission and live VFS contracts. A previously contaminated artifact cannot become authorized simply because access is restored or a new grant is created. Producer claims, attempts, leases/deadlines, evidence receipts, observation epochs and critical publication predicates remain transactional and fenced at their real mutations.

### REQ-5 — Remove inherited read fencing and verify interleaves

Description managers do not inherit blanket execution-tree serialization. Source bytes/version descriptions inside receipt-producing operations do not inherit source/root read locks, while the actual receipt/attempt transaction keeps its mutation authority. Tests cover held-writer nonblocking reads, absent/stale references, exact selected manifests, denial continuity and unchanged stale-producer/consumed-input rejection.

## Constraints and Non-Goals

- Retain latest-only catalogs; do not recreate immutable catalog history, generation/hash authority, pricing recapture, second cache authority or hidden compatibility mode.
- Reuse existing Memory revision/dependency identities; do not invent a new retention pin or publication authority to make every read latest.
- Preserve actual API failures, tenant boundaries and real operation/admission semantics.
- Static prompt lifetime, MCP discovery TTL, generic ownership/lifecycle gate removal and ordinary management authorization remain separate phases.
- No merge, deployment, security-alert dismissal or live infrastructure write.

## Acceptance

Affected deterministic database/interleave tests, backend type/lint/hooks, relevant E2E and latest-SHA CI pass. Every retained explicit lock in the affected read-facing composition must be attributed to an actual claim, capability consumption or critical persisted-state/authorization mutation; no standalone descriptive freshness gate remains.
