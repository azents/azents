---
title: "Historical Memory Phase 4: Live Memory VFS and Model-Tool Cutover"
created: 2026-10-01
updated: 2026-10-01
tags: [memory, vfs, engine, toolkit, privacy, testing]
---

# Historical Memory Phase 4: Live Memory VFS and Model-Tool Cutover

## Phase Execution Plan

- Phase: `4/6 — Live Memory VFS and model-tool cutover`
- Branch/base: `feature/historical-memory-4-memory-vfs` → `feature/historical-memory-3-vfs-platform`
- PR boundary: activate the authorized live read-only `azents://memory` backend and replace six dedicated Memory/history read tools with the generic `read`, `grep`, and `glob` surface while retaining Saved Memory mutation tools
- Inputs: Phase 2 preparation, source summaries, semantic event projection, and boundary snapshots; Phase 3 VFS registry/router/backend contracts and Runtime-independent readable-storage Toolkit; confirmed `memory-260930/REQ`; accepted ADR-D5, ADR-D9, ADR-D11 through ADR-D14; approved Design revision `1`
- Deliverables: PostgreSQL-backed Memory VFS namespace and README; Saved/Historical/source session/event/exact tool-result renderers; backend-native bounded exact read, grep, and glob with current lifecycle/privacy checks; live snapshot paths; Memory-disabled denial; final Saved-only `save_memory`/`delete_memory` domain tool surface; source lifecycle, privacy, and Runtime-independent lookup coverage
- Non-goals: Historical settings API/UI, generated public clients, frontend work, new migrations or backfill, E2E/load validation, Living Spec promotion, implementation markers, plan cleanup, deployment, merge, compatibility aliases, Memory VFS writes, or transfer/import support
- Interfaces: `VfsReadBackend` and `VfsReadContext`; canonical `azents://memory` path grammar; repository-owned bounded SQL query records; renderer-owned Markdown/text projections; common `TextReadResult`, `GrepResult`, and `VfsGlobResult`; existing boundary snapshot paths; existing Saved Memory mutation operations
- Approved Design mechanisms: `M6`, `M8`, `M9`, `M10`, `M11`, `M12`, `M14`
- Authority references: `memory-260930/REQ-1`, `REQ-2`, `REQ-5` through `REQ-8`, `REQ-10`; ADR-D5, ADR-D9, ADR-D11 through ADR-D14; current Memory, Toolkit, Agent Execution Loop, Context Compaction, and File Exchange Storage Specs; execution-owner and transaction-boundary project constraints
- Design delta: `None`
- Removal obligations: remove model exposure and implementation factories for `list_memories`, `get_memory`, `search_memories`, `search_sessions`, `read_session_history`, and `read_session_tool_result`; remove obsolete prompt/tool descriptions and tests; retain `save_memory` and `delete_memory`; retain canonical Saved/Historical/session/event repositories needed by the backend; do not add aliases
- Absence verification: tool catalog and resolver tests expose no removed names; repository search finds no removed factories or model-facing descriptions; exactly one generic `read`, `grep`, and `glob` remains; Memory backend is registry-owned, read-only, and absent when disabled; settings/API/frontend/generated-client files remain unchanged

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase contract | `/root` | `docs/azents/plans/historical-memory-phase-4-memory-vfs.md` | Phase 3 checkpoint | Frozen scope, interfaces, removals, validation, and drift boundary | Docs validation, diff check |
| Memory VFS query contract | `/root` | new repository/data modules under `python/apps/azents/src/azents/repos/`, focused repository tests | Existing Saved, Historical, Session, Event, membership, and Agent schema | Bounded typed queries for visible Saved/Historical/source/event/tool-result rows and canonical path discovery | PostgreSQL repository tests for Team/User privacy, active/archive/purge, Agent/Workspace isolation, limits, ordering, and no unbounded scan |
| Memory VFS backend and rendering | `/root` | new service/backend modules under `python/apps/azents/src/azents/services/`, `services/vfs_read.py` only where shared contracts require integration, focused tests | Phase 3 VFS interfaces and query contract | README, Saved, Historical, session, event, and exact tool-result virtual files; bounded native read/grep/glob; broad grep excludes tool-result bodies | Backend conformance and renderer tests for paths, safe fields, adjacency, truncation, deadlines, unsupported broad tool-result grep, and non-enumerating unavailability |
| Registry, composition, and snapshot guidance | `/root` | `engine/tools/deps.py`, `worker/deps.py`, `engine/tools/readable_storage.py` only if normalization requires it, `services/historical_memory/snapshot.py`, composition tests | Memory backend and existing server-created VFS context | Skills + Memory registry composition, independent enablement/authority checks, README/narrow lookup guidance, exact automatic snapshot paths | Root/subagent, Runtime unavailable, Memory disabled, owner-generation, and registry tests |
| Model-tool cutover | `/root` | `engine/tools/builtin.py`, `engine/tools/memory.py`, `engine/tools/session_history.py`, `engine/run/resolve.py`, catalogs/prompts/tests that expose removed tools | Verified Memory backend replacement | Saved mutation tools only; automatic snapshot prompt remains; six dedicated read/history tools and aliases are absent | Tool catalog snapshots, resolver tests, source absence searches, Saved save/delete regression tests, generic VFS replacement tests |
| Lifecycle, privacy, and regression | `/root` | focused Historical/Memory/Session/VFS tests across affected backend paths | All implementation workstreams | Immediate archive/access-loss denial, restore visibility, purge absence, Team/User isolation, source-linked evidence safety, unchanged Skills/Runtime behavior | Focused integration suite, full backend suite, migration/OpenAPI no-diff, structured-log privacy checks |

- Integration order: phase plan → typed bounded query contract → Memory renderers/backend → registry composition → snapshot/read guidance → dedicated-tool removal → lifecycle/privacy and absence tests → integrated validation
- Independent review: `/root/historical-memory-reviewer`; `/root` requests one read-only review only after every workstream is integrated, removals are complete, the diff is stable, and root validation passes
- Final validation: root runs docs validation and `git diff --check`; backend Ruff/format and whole-subproject typecheck; focused repository/backend/rendering/privacy/lifecycle/snapshot/toolkit/resolver tests; full backend pytest and migration suite; OpenAPI no-diff; source searches proving six removed tool names/factories are absent and Phase 5+ paths are unchanged
- Scope-drift check: implement only M6/M8/M9-M12/M14; preserve existing preparation, snapshot persistence, Saved mutation, original source evidence, Skills/Runtime VFS behavior, and public Saved CRUD; omit API/UI/settings/clients, new persistence, E2E/load/Specs, compatibility aliases, transfer support, and material failure modes absent from Design
- Context checkpoint: Phase 3 provides a reviewed registry/router/readable-storage platform and now passes the rebased full backend suite; Phase 4 activates only the approved Memory mount and cutover; Phase 5 consumes frozen read-only Historical query/service contracts for human settings; Phase 6 owns E2E/load/Spec promotion/implemented markers/plan cleanup; conditional risks are bounded PostgreSQL regex search, safe event/tool-result rendering, and exact privacy/lifecycle reauthorization
