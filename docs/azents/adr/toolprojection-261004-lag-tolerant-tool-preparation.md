---
title: "Lag-Tolerant Tool Preparation Decisions"
created: 2026-10-04
tags: [backend, engine, toolkit, concurrency]
document_role: primary
document_type: adr
snapshot_id: toolprojection-261004
---

# Lag-Tolerant Tool Preparation Decisions

Authority: [toolprojection-261004/REQ](../requirements/toolprojection-261004-lag-tolerant-tool-preparation.md), the requester-confirmed model-preparation portion of lag-tolerant read work. These decisions implement the confirmed removal boundary; they add no new product policy.

## D1 — Separate descriptive transaction capability from mutation authority

Use explicitly injected completed read-only repository scopes for saved tool snapshot, GitHub selection, Runtime and Project descriptions. Execution-owner binding applies to the existing mutation scope, not the description scope. Preserve source/namespace identity and optimistic replacement semantics. This phase does not remove the owner fence from unrelated real mutations or globally replace the Session ownership protocol.

Keeping the owner-bound manager for description would retain the rejected root-tree serialization. A process-local cache or new snapshot authority is unnecessary: existing durable descriptions already provide retained evidence. A mode flag that optionally keeps locked reads would preserve the unwanted behavior and is rejected.

## D2 — Retained Runtime and binding evidence is projection, not admission

Build model-visible Runtime targets from retained Agent capability, Runtime row, desired/applied configuration and existing Session working-folder context. Derive paths only from Runner-reported workspace evidence and the retained root Session handle. Read an existing BOUND context without locking Agent/context or binding PENDING state. Treat missing, inconsistent or invalidated evidence as unavailable.

Worktree create/remove visibility consumes the same retained descriptive evidence rather than invoking Runtime resolution/reconciliation or real-operation binding. Real Runtime/worktree admission continues to resolve and validate current exact capability, target and ownership before side effects. A projection carries an expected target, never permission to execute by itself.

Invoking `ensure_for_agent` merely with `start_if_stopped=False` is insufficient: it still reconciles and locks. Removing validation from real operation admission would change authorization and is rejected. Introducing a new authoritative cache or retained persistence schema is outside the confirmed requirement.

## Risks and Verification

Descriptions may temporarily disappear or lag concurrent lifecycle changes. That is the confirmed read contract, not a retry/fallback mode. Existing schema/executor pairing and saved source identity remain mandatory. Tests must prove projection lock absence and actual-operation stale-target rejection independently. Existing snapshot replacement fences remain a separate mutation classification for the later lifecycle phase, rather than justifying read locks.
