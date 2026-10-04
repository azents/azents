---
title: "Agent Project Catalog completed repository operations"
tags: [transaction-ownership, repository, agent-project]
created: 2026-10-05
document_role: primary
document_type: requirements
snapshot_id: ownership-261005
owner: "@Hardtack"
---

# Agent Project Catalog completed repository operations

## Authority and scope

This bounded implementation applies the approved transaction-260908 migration and current layered-architecture/database-only conventions to the historical handoff location `services/agent_project_catalog/__init__.py`.

Baseline: `f927371492631b99ed2c73cd8938d3b4740b0f5c`, branch `fix/agent-catalog-ownership-261005`. This snapshot preserves currently reachable behavior; it does not introduce new project authority or claim combined verification with another Session's uncommitted lifecycle-fence work.

## Confirmed outcomes

- REQ-1: Services sequence complete repository operations and Runtime probes. No service receives a live SQL session, opens a transaction, imports SQLAlchemy/RDB or supplies a callback executed inside a repository scope.
- REQ-2: Candidate upsert/list/path selection and status persistence preserve exact Agent ID and normalized absolute Agent Workspace paths, existing deduplication/order/limit behavior, catalog identity and status domain outputs.
- REQ-3: Independent catalog lists use native database-enforced read-only scopes and detached results; mutation groups use native write scopes.
- REQ-4: Batch candidate insertion and batch status application remain atomic; exceptions/cancellation roll back partial catalog effects.
- REQ-5: Runtime target resolution, file-stat probes and pure path normalization occur outside every open database transaction.
- REQ-6: Execution-owned status application retains its exact Session owner-generation fence and current stale-generation failure before writing. No new actor predicate, admission lock or generation check is invented beyond baseline authority.
- REQ-7: Existing public service methods and result/error contracts remain stable. Runtime probe unavailable/generation/failure handling remains unchanged.
- REQ-8: The other Session's same-file diff is read-only integration evidence only. Its removal of the baseline execution-specific method must be reconciled with its owning call-path changes when an exact owner commit/PR is available; this delivery must not claim those combined changes verified.

## Acceptance evidence

- Existing focused catalog service/repository tests, including owner takeover between Runtime evidence and final status application.
- Real PostgreSQL read-only and nonblocking catalog reads, same-path concurrent identity persistence, exact Agent isolation, atomic batch rollback/cancellation and detached results.
- Runtime/file-stat proof that no DB transaction remains open when probes run.
- Native hooks/type/OpenAPI completion, exact commit and clean working tree.

## Exclusions and coordination

No source edits in the other Session, no uncommitted fence copying, no changes to shared narrow repositories or baseline lock/CAS semantics, no public schema/migration changes, and no subagents. Root owns Living Spec/PR/integration and the full #1718 completion decision.
