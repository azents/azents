---
title: "Lag-Tolerant Management Requirements"
created: 2026-10-04
tags: [backend, concurrency, authorization, management]
document_role: primary
document_type: requirements
snapshot_id: manageguard-261004
---

# Lag-Tolerant Management Requirements

## Primary System Outcome

Ordinary management and authorization descriptions tolerate committed lag without explicit parent/FK/ancestor locks. Actual security and exact-target mutations preserve existing public outcomes with operation-scoped protection rather than broad descriptive serialization.

## Confirmed Scope

This snapshot represents the ordinary-management phase of the requester-confirmed defensive-lock removal sequence. The requester directed continued implementation after the session-capability foundation. Existing permissions, last-administrator/credential safeguards, one-time authentication and exact-resource mutation outcomes remain requirements, not newly proposed product behavior.

## Requirements

### REQ-1 — Ordinary descriptions are nonblocking

Workspace/User membership, Agent/Session, Toolkit/integration, registered Project, Runtime Profile/Provider and external-channel configuration/identity descriptions use scoped ordinary reads. Pure getters have no hidden lock mode or parent-read lock inheritance. Missing/deleted or older references remain existing unavailable outcomes without hidden initialization or read repair.

### REQ-2 — Authorization and mutation identity stay exact

Retain exact Workspace/Agent/resource and existing actor-role checks. Obsolete ordinary non-owner updates/deletes cannot demote or delete a newly assigned Workspace Owner. Ownership transfer and other dependent security-state mutations remain coherent. Preserve existing conflict/NotFound/OwnerLocked semantics rather than introduce client versions or recovery policies.

### REQ-3 — Administration safeguards remain narrow and correct

Concurrent system administrator revocation/User deletion cannot leave zero administrators; credential removal retains a usable credential. Runtime Profile/Provider/System Settings mutation uses existing expected version, source/reference and constraint outcomes without partial policy replacement. Read/list and ordinary unrelated operations do not inherit these critical guards.

### REQ-4 — External authentication and Runtime Web guarantees remain

One-time OAuth/ticket/binding consumption, exact credential finalization and configuration-change fail-closed identity issuance remain correct. Runtime Web concurrent activation respects the existing hard quota. Stale configuration or target evidence cannot authorize a delayed identity/resource mutation. These are exact mutation/admission guarantees, not a blanket exemption for surrounding reads.

### REQ-5 — Close shared caller boundaries

Account for ordinary and critical callers of changed shared authorization/getter helpers. Preserve execution claims, lifecycle/resource-generation finalization and producer publication in their own later phase or exact exception. Verify successful read-only paths under held-writer locks and deterministic concurrent OWNER/admin/credential/configuration/quota/version outcomes.

## Constraints and Non-Goals

- No relaxed authorization, quota, last-admin/credential or one-time capability contract.
- No new public API version field, database authority/schema, compatibility fallback, retry mode or rollout toggle.
- PostgreSQL ordinary write locks, foreign keys, uniqueness and transaction atomicity remain available.
- Catalog/Memory, generic execution/lifecycle gate removal, static prompts, discovery frequency and latency diagnosis remain separate work.
- No Agent merge, deployment, security-alert dismissal or live infrastructure mutation.

## Acceptance

Affected deterministic concurrency/read-only tests, type/lint/hooks, applicable API/E2E and latest-SHA CI pass. Every remaining explicit lock in affected ordinary-management compositions has a precise claim, consumption or critical obsolete-result/security-state mutation justification; descriptive freshness alone does not qualify.
