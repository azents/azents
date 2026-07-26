---
title: "Runtime Execution Profiles Phase 6 Product UI Execution Plan"
created: 2026-07-26
tags: [runtime, execution-policy, admin, workspace, agent, ui]
---

# Phase Execution Plan

- Phase: `6 — product UI and safe execution-status projection`
- Branch/base: `feature/runtime-execution-profiles-08-product-ui` → `feature/runtime-execution-profiles-07-gateway-engine`
- PR boundary: Admin, Workspace, and Agent Runtime Execution operational surfaces plus the narrow server-authoritative read projection required to render configured, pending, applied, unavailable, and divergent state without client inference.
- Inputs: `runtime-260726/REQ`, `runtime-260726/ADR`, `runtime-260726/DESIGN`, implementation plan, Phase 2 management APIs/generated clients, Phase 3 Apply/Control evidence, Phase 4/5 capability and gateway contracts.
- Deliverables:
  - An Admin `Runtime Execution` surface adjacent to Runtime Providers for Platform limits, Profile lifecycle, current version/digest, and safe audit history.
  - A Workspace `Runtime execution` surface that displays allowed/available Profiles, Workspace restrictions, bounded unavailability reasons, audit history, and a role-aware edit mode.
  - An Agent `Execution environment` settings surface with distinct configured, pending, applied, unavailable, and divergent views; versioned intent save; explicit Apply; hierarchy reductions and governing-layer explanations; and safe audit history.
  - A narrow Public API execution-policy status projection on Agent Runtime reads, plus generated clients, that supplies configured/pending/applied/unavailable/divergent status, configured/applied Profile identity, target/applied digest, desired generation, capability summaries, storage/network summary, governing layer/reason codes, and bounded required action.
  - Loading, empty, error, version-conflict, read-only, mobile, and overflow states plus focused component/container tests and stories.
- Non-goals:
  - No new policy semantics, authorization rules, runtime lifecycle behavior, Provider capability enablement, gateway behavior, or direct infrastructure controls.
  - No UI-derived policy, status, or permission decisions. Server responses remain authoritative.
  - No Provider credentials, socket paths, Kubernetes names, secret values, privileged controls, raw policy manifests, or implementation-specific diagnostics in any UI/API projection.
  - No privileged-engine capability advertisement or selection while its capability contract remains unavailable.
- Interfaces:
  - The safe execution-status projection is read-only and derives from existing configured settings, target/applied snapshots, Runtime desired/observed state, and existing bounded reason codes. It does not create snapshots, mutate intent, advance generation, or expose evidence secrets.
  - Admin, Workspace, and Agent writes continue to use existing expected-version APIs. Save updates Agent intent only; Apply remains a separate owner/admin action that creates the Runtime target.
  - UI containers map generated API clients to discriminated state models. Components never reconstruct pending/applied/divergent state from digest or generation fields.
  - Workspace MEMBER access is read-only and OWNER/MANAGER edit visibility is presentational only; backend authorization remains final.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Safe status projection and generated clients | `/root/runtime-execution-implementer` | `python/apps/azents/src/azents/api/public/**`; existing execution-policy service/read-model paths; public OpenAPI artifacts; `python/libs/azents-public-client/**`; `typescript/packages/azents-public-client/**`; associated tests | Phase 3 applied evidence and existing Runtime read model | Read-only status projection and regenerated clients | Backend route/service tests; OpenAPI dump/regeneration; Python and TypeScript generated-client checks |
| Product UI | `/root/runtime-execution-implementer` | `typescript/apps/azents-admin-web/**`; `typescript/apps/azents-web/**`; associated tests/stories | Generated clients and safe projection | Admin/Workspace/Agent operational views and responsive state handling | Format/lint/typecheck/build; focused tests/stories |
| Integration and phase documents | `/root` | `docs/azents/plans/runtime-execution-profiles-phase-6-product-ui.md`; localized integration/review fixes only after owner report | Implementer output | Scope verification, review, commit, and PR creation | Plan/diff scope check, primary verification |

- Integration order:
  1. Add and test the safe server read projection, dump OpenAPI, and regenerate Public clients before hand-written UI uses the contract.
  2. Add Admin Platform/Profile/audit screens using existing Admin client patterns.
  3. Add Workspace restrictions/Profile availability/audit screen using generated Public client patterns.
  4. Add Agent configured/pending/applied status, versioned save, explicit Apply, and audit views using the safe Runtime projection.
  5. Add state stories and focused tests for loading, empty, read-only, conflict, unavailable, divergent, pending expansion, and applied states.
  6. Run backend/client/frontend validation and targeted review of authorization/state/secret exposure boundaries.

- Independent review: `/root/runtime-execution-reviewer` performs a read-only review focused only on Requirements/Design mismatch, UI/API authorization bypass, client-side lifecycle or status inference, accidental mutation from read routes, secret/Provider topology exposure, incorrect Apply versus save behavior, privileged capability misrepresentation, and material convention violations. Batch required findings once; targeted re-review only for those high-risk corrections.

- Final validation:
  - Backend Ruff/format/Pyright and focused route/service tests.
  - OpenAPI dump plus Public Python and TypeScript client generation and type checks.
  - Admin Web and main Web format, lint, typecheck, build, focused unit/container tests, and relevant stories.
  - Authorization/read-only/version-conflict tests and safe-projection field exclusion tests.
  - `git diff --check` and pre-commit on commit. Do not monitor CI until the complete stack exists.

- Scope-drift check: Compare the complete Phase 6 diff against `feature/runtime-execution-profiles-07-gateway-engine`. Reject direct infrastructure configuration, client-side state inference, status mutation from read paths, Provider secret/topology exposure, UI authority bypass, generic privileged/image controls, generated-client hand edits, gateway/Engine behavior changes, and unrelated refactors. Confirm status fields come exclusively from a bounded server-authoritative projection and that Apply is visibly and behaviorally separate from save.
