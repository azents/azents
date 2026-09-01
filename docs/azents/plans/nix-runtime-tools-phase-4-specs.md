---
title: "Persistent Runtime System Tools Phase 4 Spec Promotion Plan"
created: 2026-09-01
tags: [runtime, package-management, nix, documentation, spec, cleanup]
---

# Persistent Runtime System Tools Phase 4 Spec Promotion Plan

## Phase Execution Plan

- Phase: `4/4 — Living Spec promotion and plan cleanup`
- Branch/base: `feature/nix-runtime-tools-4-specs` → `feature/nix-runtime-tools-3-validation`
- PR boundary: Promote the verified persistent Nix Runtime behavior into current Living Specs, mark both completed development snapshots implemented on the same date, and remove the temporary feature implementation plans.
- Inputs: Phase 1 Provider storage PR `#1584`, Phase 2 Runner/addon PR `#1591`, Phase 3 validation PR `#1593`, confirmed `runtime-260831/REQ`, accepted `runtime-260831/ADR`, approved `runtime-260831/DESIGN` revision `1`, superseding `nix-260831` Requirements/ADR/Design revision `1`, and Phase 3 validation/review evidence.
- Deliverables: Current Specs describe native user-managed Nix guidance, Provider-owned persistent `/nix` storage, Kubernetes and Docker lifecycle semantics, Workspace separation, and the combined required E2E/Provider-conformance gate. Both Requirements and Design snapshots receive `implemented: 2026-09-01`. All `nix-runtime-tools-*.md` plans are removed after the promotion is verified.
- Non-goals: Product code changes, API/OpenAPI/client changes, new package-management behavior or authority, CI behavior changes, retrospective ADR edits, implementation-history duplication in Living Specs, or PR merge.
- Interfaces: Current implementation at Phase 3 commit `4e6e5de1b`; native `nix search` and `nix profile add`; Provider-owned Workspace and Nix storage; existing reset/terminal-delete boundaries; Runtime Toolkit prompt; Workspace file/download authorization; required CI gates.
- Approved Design mechanisms: `runtime-260831/M1`–`M10` and `nix-260831/M1`–`M5`.
- Authority references: `runtime-260831/REQ-1`–`REQ-8`, `runtime-260831/ADR-D1`–`ADR-D5`, `runtime-260831/DESIGN`; `nix-260831/REQ-1`–`REQ-4`, `nix-260831/ADR-D1`, `nix-260831/DESIGN`; current Agent Runtime Persistence, Runtime Provider, Toolkit, Agent Runtime Control, and E2E-Primary Test Strategy Specs.
- Design delta: `None`
- Removal obligations: Remove the temporary multi-phase implementation plan and Phase 1–4 execution plans after their durable behavior is represented by Living Specs and the two snapshots are marked implemented.
- Absence verification: Confirm no `docs/azents/plans/nix-runtime-tools-*.md` remains; generated documentation indexes contain no stale plan entries; current Specs do not claim a Runtime capability/Profile/API/Admin package setting, package inventory, wrapper, daemon, Platform package-policy enforcement, Workspace-backed `/nix`, or compatibility fallback.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Spec impact and promotion | `/root` | `docs/azents/spec/domain/toolkit.md`, `docs/azents/spec/domain/runtime-provider.md`, `docs/azents/spec/flow/agent-runtime-persistence.md`, `docs/azents/spec/flow/test-strategy-e2e-primary.md` | Verified Phase 1–3 implementation | Current behavior, code paths, versions, verification dates, and changelogs | Implementation/spec comparison, docs validation, targeted searches |
| Snapshot completion | `/root` | `docs/azents/requirements/runtime-260831-persistent-system-tools.md`, `docs/azents/design/runtime-260831-persistent-system-tools.md`, `docs/azents/requirements/nix-260831-user-managed-runtime-tools.md`, `docs/azents/design/nix-260831-user-managed-runtime-tools.md` | Complete validation and no material Design delta | Matching `implemented: 2026-09-01` dates without rewriting accepted decisions | Snapshot validator and frontmatter checks |
| Plan cleanup | `/root` | `docs/azents/plans/nix-runtime-tools-*.md` | Successful Spec and snapshot promotion | No temporary feature plans remain | Tracked-file search and generated index validation |
| Phase review and PR | `/root` | Complete documentation diff | Stable promotion diff | Independent documentation review, commit, push, and `[4/4]` stacked PR | `hardtack` review, pre-commit, `git diff --check` |

- Integration order: record and commit this Phase 4 plan → compare Phase 1–3 implementation with matched current Specs → update behavior text/frontmatter/changelogs → add matching implemented dates to both snapshot pairs → validate authority/removal absence → remove every Nix Runtime Tools plan including this plan → request `hardtack` documentation review → apply required corrections → run final docs/pre-commit checks → commit, push, and open the Phase 4 PR before monitoring the complete stack CI.
- Independent review: exact reviewer `hardtack`; read-only review against both Requirements/ADR/Design snapshots, Phase 1–3 implementation and validation evidence, the four promoted Specs, matching implementation dates, absence of historical ADR rewrites, and complete plan removal.
- Final validation: targeted implementation/spec searches; snapshot/frontmatter validation through pre-commit; documentation index regeneration through commit hooks; `git diff --check`; exact plan absence search; stacked PR CI after PR creation.
- Scope-drift check: The PR may describe only reachable current behavior and remove temporary plans. Any product code, new material behavior, changed authority, compatibility promise, rollout mechanism, or package-policy control plane is out of scope.
- Context checkpoint: Phase 1 implements Provider-owned Kubernetes/Docker Nix storage, Phase 2 implements the native user-managed Nix Runner and prompt, and Phase 3 adds reviewed product and Provider validation. Phase 4 changes documentation only, establishes `2026-09-01` as the completed snapshot date, removes temporary plans, and leaves merge decisions to explicit requester approval.
