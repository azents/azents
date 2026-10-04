---
title: "Lag-Tolerant Tool Preparation Requirements"
created: 2026-10-04
tags: [backend, engine, toolkit, performance, concurrency]
document_role: primary
document_type: requirements
snapshot_id: toolprojection-261004
---

# Lag-Tolerant Tool Preparation Requirements

## Primary System Outcome

Preparing model-visible tool descriptions uses retained descriptive evidence without acquiring execution-owner/tree locks or reconciling Runtime configuration. Approximate availability never grants authority for a real side effect.

## Confirmed Scope

This snapshot records the model-preparation phase of the requester-confirmed lag-tolerant read and defensive-lock removal work. The requester directed completion of the broad session-capability PR first, followed by the remaining phases, on 2026-10-04. It does not introduce another approval workflow or change public operation contracts.

## Requirements

### REQ-1 — Saved tool descriptions do not serialize ownership

MCP-family saved tool snapshots and GitHub selection reads complete without locking the Session execution tree. They retain exact Agent, Session, namespace and saved source identity checks. Missing descriptive state is a normal absent result. Prepared schemas and their executors remain paired for the same call.

### REQ-2 — Runtime description does not reconcile

Runtime capability, target, working-folder and Project descriptions for model preparation use retained evidence. Preparation neither initializes a Runtime nor performs configuration reconciliation, binding compare-and-swap, or explicit parent/row locking. Missing, pending, invalidated or unready evidence remains unavailable for projection.

### REQ-3 — Worktree availability is descriptive

Create/remove worktree visibility uses eligible retained Runtime and Session evidence without invoking real-operation admission or reconciliation. Removal visibility still requires a retained ready managed allocation. Availability may lag concurrent changes.

### REQ-4 — Actual admission remains authoritative

Every actual Runtime or worktree operation keeps its existing current capability, permission, exact target/generation, Session binding and ownership validation before external side effects. A stale projection cannot act on a replacement resource or bypass revocation. Snapshot persistence and other mutations are classified separately from projection reads; this phase does not globally dismantle mutation fences.

### REQ-5 — Verify structural and performance outcomes

Tests prove the projection paths emit no explicit locks, do not invoke reconciliation or pending binding, tolerate absent/stale descriptions, and preserve real-operation rejection. Record comparable model-preparation latency observations, including p95/p99 and the measured workload, without promising an improvement magnitude before measurement.

## Constraints and Non-Goals

- Preserve public APIs, source identity, schema/executor consistency and real-operation failure behavior.
- No new discovery TTL, cache authority, schema, configuration switch, legacy fallback, retry policy or static-prompt lifetime change.
- Catalog/Memory coherence, ordinary management, broad lifecycle gates, static prompts, MCP discovery frequency and operational blocking-stack diagnosis remain separate work.
- No live deployment, merge, infrastructure write or security-alert dismissal.

## Acceptance

Affected unit/concurrency and integration tests, backend type/lint/hooks, relevant E2E and latest-SHA CI pass. Pure projections can run through read-only capabilities and perform only database reads within their completed transaction boundaries. External I/O remains outside those boundaries.
