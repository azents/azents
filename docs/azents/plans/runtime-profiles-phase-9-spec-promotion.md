---
title: "Workspace-Owned Runtime Profiles Phase 9 Spec Promotion Plan"
created: 2026-07-31
updated: 2026-07-31
tags: [runtime, provider, workspace, profile, documentation, spec]
---

# Workspace-Owned Runtime Profiles Phase 9 Spec Promotion Plan

## Phase Execution Plan

- Phase: `9 — Spec promotion`
- Branch/base: `feature/runtime-profiles-09-spec-promotion` →
  `feature/runtime-profiles-08-validation`
- PR boundary: promote the validated Workspace-owned Runtime Profile replacement into current
  living specs and mark the completed Requirements and Design snapshot implemented.
- Inputs: completed Phase 8 validation report; `runtime-260730/REQ`, `runtime-260730/ADR`,
  `runtime-260730/DESIGN`; current Agent, Workspace, Runtime Provider, Runtime Control, and Runtime
  Persistence specs.
- Deliverables: current specs describe one exact Workspace-owned Runtime Profile authority; the
  Requirements and Design share `implemented: 2026-07-31`; code paths, verification dates, versions,
  and changelogs match the implemented system.
- Non-goals: product behavior changes, API or generated-client changes, new ADR decisions, plan
  deletion, historical snapshot rewrites beyond the implementation marker, or production rollout.
- Interfaces: exact Agent Profile selection; Workspace catalog/default/recreation; Provider-owned
  infrastructure Profiles and current capability authority; desired/applied configuration
  revisions; Provider/Runner evidence; storage-preserving lifecycle and explicit recreation.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Spec impact confirmation | `/root` | Complete stack diff and `docs/azents/spec/**` | Phase 8 validation report | Final impacted-spec set and stale-authority inventory | `/spec-review` comparison and repository search |
| Domain spec promotion | `/root` | `docs/azents/spec/domain/agent.md`, `workspace.md`, `runtime-provider.md` | Validated domain/API behavior | Current Agent selection, Workspace ownership/default, Provider/Profile authority, and recreation descriptions | Frontmatter validation, code-path checks, and terminology search |
| Flow spec promotion | `/root` | `docs/azents/spec/flow/agent-runtime-control.md`, `agent-runtime-persistence.md` | Validated lifecycle, evidence, Provider, and storage behavior | Current desired/applied reconciliation, exact evidence, recreation, and persistence behavior | Cross-check against E2E/provider/backend evidence |
| Snapshot completion | `/root` | `docs/azents/requirements/runtime-260730-workspace-owned-runtime-profiles.md`, `docs/azents/design/runtime-260730-workspace-owned-runtime-profiles.md` | All implementation and Phase 8 validation complete | Matching implementation date without changing accepted intent or ADR | Snapshot validator and immutable ADR diff check |
| Independent review | `hardtack` | Read-only Phase 9 diff | Stable promoted specs | Review for authority ambiguity, stale fallback, data-loss semantics, and snapshot lifecycle | GitHub review request and targeted re-review only for material findings |

- Integration order: store this plan; confirm spec impact against the complete implementation diff;
  replace stale domain authority descriptions; replace stale control/persistence flow descriptions;
  update code paths, verification dates, versions, and changelogs; add the matching implementation
  date to Requirements and Design; run terminology, snapshot, documentation, and diff checks.
- Independent review: `hardtack` compares the promoted specs with the Phase 8 validation report,
  E2E behavior, migration/removal evidence, accepted ADR, and immutable completed snapshot rules.
- Final validation:
  - documentation frontmatter/index and snapshot validation through pre-commit;
  - `git diff --check`;
  - repository search for stale execution-policy, Apply, Provider preference/default, accepted
    capability, policy snapshot, and fallback descriptions in current specs;
  - explicit confirmation that `docs/azents/adr/runtime-260730-workspace-owned-runtime-profiles.md`
    is unchanged;
  - spec `code_paths` existence checks for every promoted document.
- Scope-drift check: the diff contains documentation-only current-spec promotion plus matching
  Requirements/Design implementation markers and this temporary phase plan. No source, migration,
  API, generated artifact, or behavior change is allowed.
- Context checkpoint: Phase 8 passed real Docker Provider E2E, complete migration validation,
  focused backend and full Provider/control suites, and active-source absence checks. The validation
  report identifies five stale living specs and no missing product implementation. The accepted ADR
  remains immutable. The next phase after this PR is documentation-plan cleanup only.
