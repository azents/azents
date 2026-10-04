---
title: "Completed model, policy, subscription and Project manifest database operations"
created: 2026-10-05
tags: [backend, repositories, transactions]
document_role: primary
document_type: requirements
snapshot_id: ownership-261005
---

# Requirements

Authority: `transaction-260908/REQ-1` through `REQ-4`, adopted `transaction-260908-repository-ownership.md`, current Living Specs and requester-approved #1718 remediation. This is a bounded implementation slice, not a new product design decision.

## REQ-1 — Completed model availability operations

Move Session model authorization, health reads, reservation claim/update and generation-fenced cancellation into a composing repository. Read operations use the native read-only manager; related mutations use one completed write scope. Preserve active root/user/workspace authority, claim CAS, ordered first healthy fallback, server time, conflicts, cancellation and unchanged DTO wire representation.

## REQ-2 — Subscription usage ingress read closure

A composing read-only repository returns the detached integration and decrypted typed secrets. Preserve missing integration versus foreign Workspace failures and every provider-specific status/freshness/financial projection. OAuth freshness, refresh/retry and HTTP usage reads run only after the initial read scope closes. Existing OAuth persistence operations remain repository-owned.

## REQ-3 — Agent automatic Project policy authority

Policy reads and final replacement belong to a composing repository. Preserve explicit AgentAdmin and Workspace scope, coherent policy/revision reads, ordered normalization/de-duplication, empty clear without Runtime, Runtime directory validation after read closure, and one atomic policy/catalog update. Revalidate necessary Agent/Workspace/admin authority after Runtime validation before the final write. Rejected revision, SQL failure or cancellation leaves policy and catalog unchanged.

## REQ-4 — Project browser manifest preparation

Return detached authorized Session/Project/worktree/catalog facts from distinct completed read-only repository operations. Keep Session binding and Runtime target resolution outside DB scopes; perform final required DB authorization again on post-Runtime manifest reads. Preserve stored/unchecked catalog presentation, ordering, filesystem action capabilities, Runtime workspace-root validation and non-blocking refresh hints; do not introduce filesystem probes inside transactions.

## REQ-5 — Scope and verification

Own only the four assigned services and exact tests plus new distinct composing repository/data modules and necessary defining-module import/DI closure coordinated with root. No low-level repository rewrite, callbacks around live sessions, repository imports from services, SQLAlchemy/manager handles in the services, other Session dirty Agent Project Catalog or Runtime Control edits. Current specs are updated by root from an external exact proposal. Use focused real PostgreSQL auth/CAS/failure/cancellation proofs and service tests, native commit hooks and one bounded commit; root owns PR shipping and no merge is authorized.
