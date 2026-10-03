---
title: "Agentic Historical Memory Phase 4: Context and Cutover"
created: 2026-10-04
tags: [memory, engine, backend, implementation]
---

# Phase Execution Plan

- Phase: 4 — whole-document foreground context, live VFS, coordinated handover.
- Branch/base: `feat/memory-261002-4-context-cutover` → `feat/memory-261002-3-consolidation` (PR #2089, `aa00517f5`).
- PR boundary: exact aggregate snapshot selection/filtering, authorized live lookup, bounded revision collection, explicit forward/rollback/reactivation reset operations and rehearsals.
- Inputs: Phase 3 shared-core internal host, immutable publication/dependencies, source availability/grant continuity, root Run/compaction hooks and foreground continuation reset.
- Deliverables: complete independently validated 10,000-byte blocks; at most two blocks/20,000 Historical bytes; strict new snapshot kind/version; no ordinary-turn reselection; latest live read-only aggregate aliases; coordinated offline reset and reactivation reconciliation.
- Non-goals: merge/deployment/live migration or cutover, new settings or API CRUD, dual mode, old snapshot compatibility, source-packing fallback, generation during foreground preparation, Saved changes or history deletion.
- Interfaces: current foreground consumer resolves root authority; exact unit identity binds Team/personal aliases; selected revision owns its dependency checks; Toolkit State CAS/unchanged-content reuse stay intact; existing admission/drain procedures are prerequisites to offline handover operations.
- Approved Design mechanisms: M12–M15, integrated with M3/M6/M9/M10/M11.
- Authority: [memory-261002/REQ](../requirements/memory-261002-consolidated-history.md) REQ-2–REQ-8; [ADR](../adr/memory-261002-consolidated-history.md) D6/D8/D9/D10/D13; [approved Design revision 2](../design/memory-261002-consolidated-history.md), Privacy/Invalidation, Read APIs, Migration/Rollback and Removal/Replacement sections.
- Design delta: **None**.
- Removal obligations: replace automatic source ranking/dedup/packing, old snapshot entry schema and candidate cap. Retain canonical source inventory/preparation, original-history reads, Saved CRUD, root/child histories and all foreground event semantics.
- Absence verification: searches for `_select_historical_entries`, old automatic source candidates and permissive `schema_version >= 1`; strict decoder rejection tests; ordinary-turn/latest-live separation; reset never mutates canonical Saved/source bodies or Run/Session identity/status.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Aggregate authority | `/root` | `repos/historical_memory_consolidation/foreground.py`, tests; `cleanup.py`, tests | Phase 3 manifests | Current and exact-revision lookup, dependency-safe GC | PostgreSQL purge/revoke/restore and old-selected-revision tests |
| Boundary assembly | `/root` | `core/historical_memory_{snapshot,context}*`; `repos/memory_context_snapshot.py`; `services/historical_memory/{snapshot,context_snapshot}*` | Foreground lookup | Strict kind/version, whole blocks, CAS and refresh boundaries | Byte limits, empty outcomes, child inheritance, no reselection |
| Live Memory VFS | `/root` | `services/memory_vfs*`; related VFS repository contracts only if needed | Foreground lookup | Team/personal aliases, authorized glob/grep | No Runtime, private/peer non-enumeration, newest live bytes |
| Handover | `/root` | `core/historical_memory_cutover.py`; `repos/historical_memory_consolidation/cutover*`; `services/historical_memory/cutover*`; `cli/memory_handover*`; handover rehearsal record | New snapshots and source enrollment | Explicit quiesced bounded reset, fence, reconciliation | Forward/reverse/reactivation with interrupted root/child histories and Saved preservation |
| Integration | `/root` | This plan; provider-continuation regression tests; Saved/source repository and Memory VFS contracts/tests; discovery cleanup counters; synthetic context fixtures; existing required source-preparation E2E packing assertion | All workstreams | Stable reviewed dependent PR | Root full backend and focused continuation/VFS matrices |

- Integration order: exact-revision reader → strict snapshot/whole composition → live VFS → collection → explicit handover/reconciliation → integrated checks → freeze/review/correction → commit/PR.
- Independent review: `/root/memory-implementation-reviewer`, read-only on complete stable integrated phase diff; root owns corrections and validation.
- Final validation: root runs Ruff/format/Ty, full backend Pytest with disposable PostgreSQL/Redis, docs catalog and whitespace; targeted native Memory prefix reset, snapshot boundary/CAS and VFS checks. Full deterministic product E2E and capacity report remain Phase 5.
- Scope drift: verify every M12–M15 behavior, removal and source/Saved preservation; reject peer-budget hints, implicit transition, mixed readers, hidden fallback, new authority or persisted mode.
- Context checkpoint: Phase 3 committed/PR-created, 7,406 backend tests passed/3 skipped, independent review clear. No Phase 4 implementation yet. Goal remains active through Phase 5 and final-SHA authored stack CI; no external action is authorized.

## Root Integration Checkpoint

- Replaced the source-packing candidate query/DTO, topic ranking/deduplication and permissive snapshot decoder with exact `consolidated_memory` version 2. Each selected immutable revision keeps its own validated whole block, scope/provenance and complete manifest. Ordinary turns reauthorize those exact references without reading the latest pointer as substitute authority.
- Updated the existing Stage 1/source-lookup required E2E assertion to verify that prepared source rows are not automatically packed when no authored aggregate exists. Its full settings/read/glob/grep/lifecycle/Runtime-denial flow remains; genuine multi-turn consolidation proxy/product coverage still belongs to Phase 5.
- Boundary assembly concatenates canonical envelopes without Historical framing outside the independent budgets; the separate prefix contains only common/Saved guidance. The new 10k/10k, single-unit and whole-unit filtering tests use multilingual exact-byte fixtures.
- Moved snapshot transaction composition into `MemoryContextSnapshotRepository`; the service delegates complete operations. Preserved root Run start, committed compaction, CAS, unchanged-content reuse and child-root inheritance. Bounded unconfirmed authority yields no Memory contribution rather than a generation wait or unsafe continuation.
- Added live read-only Team/personal aliases with exact actual-root authorization, current manifests, non-enumerating absence, provenance, glob/grep and no Runtime. Full generic source inventory remains body-free; the root consumer projection was narrowed to authority fields.
- Added bounded revision collection that protects current pointers and retained automatic references, share-locks selected bytes through snapshot commit, skips competing owners and rechecks references after exclusive lock acquisition. Independent manifests remain with protected old revisions.
- Implemented explicit quiesced forward/rollback/reactivation CLI and bounded database-only operations. Rehearsal preserves Saved/canonical sources and interrupted root/child Run IDs/phase/status/history; rollback leaves additive storage inert, while reactivation discards all old derived state even for matching hashes and reconciles old-code writes without Stage 1 extraction.
- Root evidence: initial boundary matrix **21 passed**; handover/CLI/manifest matrix **20 passed**; broad Memory/storage/VFS/shared-core/hook matrix **354 passed**; final corrected boundary/foreground/handover/prefix/CLI matrix **29 passed**. These overlap and are not summed unique coverage. Whole-backend Ruff/format/Ty pass. Full backend is next, followed by this feature's same independent reviewer.
- Final root-owned full backend Pytest: **7,419 passed, 3 skipped** in 313.77 seconds (Python 3.14; disposable PostgreSQL 17/Redis). Final focused matrix is **29 passed**, including bounded authority absence and strict unexpected-error propagation. Backend Ruff/format/Ty, E2E-subproject Ty and touched-file Ruff/format, documentation catalog and whitespace checks pass. Product E2E execution/expanded proxy remains an explicit Phase 5 obligation; static checks are not reported as E2E execution.
- No public route/schema, toggle, persisted rollout mode, fallback, dual writer, provider orchestration, epoch authority or live action was added. `Design delta: None`. The same `/root/memory-implementation-reviewer` completed the full independent review with **Review-clear** and no grounded actionable finding; all 31 frozen hashes/deletion markers matched at start/end (manifest SHA256 `870d540f2b354bbbcbdc47371006ec2b8215c6d792152afe5cc96bf6895c2681`). Root is committing and opening the dependent Phase 4 PR next. Phase 5 has not started and begins only after that PR exists.
