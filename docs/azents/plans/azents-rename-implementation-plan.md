---
title: "Azents rename implementation plan"
created: 2026-05-26
tags: [architecture, infra, backend, frontend, testenv, documentation]
---

# Azents rename implementation plan

## Source of truth

- Design: `docs/azents/design/azents-rename-plan.md`
- Tracking issue: <https://github.com/azents/azents/issues/4079>

This plan defines stacked PR boundaries for the Azents to Azents rename. It
does not include per-file implementation checklists for each phase. Each
implementation phase adds its own detailed phase plan under `docs/azents/plans/`.

## Stack shape

```text
main
  <- codex/azents-rename-contract
  <- codex/azents-rename-impl-plan
  <- codex/azents-rename-python-proto
  <- codex/azents-rename-generated-clients
  <- codex/azents-rename-typescript-ui
  <- codex/azents-rename-dart
  <- codex/azents-rename-nondurable-infra
  <- codex/azents-rename-testenv-docs
  <- codex/azents-rename-verification
  <- codex/azents-rename-spec-promotion
  <- codex/azents-rename-cleanup
```

Durable data resources are intentionally excluded until the final cutover
runbook phase. Before that phase, Azents workloads use new `AZ_*` config names
while still pointing at existing Azents RDS and object-storage resources.

## Phase 1: Rename contract

Branch: `codex/azents-rename-contract`

Purpose:
- Record the naming contract.
- Record durable-data-last sequencing.
- Record latest-main feasibility notes.

Input:
- User decision to rename Azents to Azents.
- User decision to defer DB/S3 rename to the final step.

Output for next phase:
- A reviewed design document that defines rename scope and sequencing.

Verification:
- azents docs index check.

## Phase 2: Multi-phase implementation plan

Branch: `codex/azents-rename-impl-plan`

Purpose:
- Define stacked PR boundaries.
- Map each rename area to a reviewable phase.
- Define verification matrix and durable data cutover gate.

Input:
- Phase 1 design document.

Output for next phase:
- This implementation plan.
- Branch names and base relationships for the stack.

Verification:
- azents docs index check.

## Phase 3: Python backend and runtime protocol rename

Branch: `codex/azents-rename-python-proto`

Purpose:
- Rename Python package and module identifiers that define backend and runtime
  interfaces.
- Rename protobuf package/path and regenerate generated protobuf Python code.
- Rename backend environment prefix handling from `AZ_` / `AZENTS_` to `AZ_`
  without compatibility aliases.

Boundary:
- Includes Python apps/libs and proto sources.
- Excludes generated OpenAPI API clients except where source OpenAPI generation
  requires backend package path updates.
- Excludes TypeScript UI package rename.
- Excludes durable data resource creation or rename.

Input from previous phase:
- Naming contract and phase plan.

Output for next phase:
- Backend/runtime code imports use Azents identifiers.
- Runtime provider/runner env vars use `AZ_*`.
- Proto package is `azents.runtime_control.v1`.

Verification scope:
- Affected Python unit tests where feasible.
- `uv run ruff check --fix . && uv run ruff format .` for affected Python
  subprojects.
- `uv run pyright` for affected Python subprojects where feasible.
- Protobuf generation check.

## Phase 4: Generated clients and OpenAPI rename

Branch: `codex/azents-rename-generated-clients`

Purpose:
- Regenerate Python and TypeScript API clients from renamed OpenAPI specs.
- Rename generated client package names and import paths.

Boundary:
- Includes generated client packages and generator config.
- Includes OpenAPI title/description changes.
- Excludes hand-written frontend UI copy changes except imports required to
  consume renamed clients.

Input from previous phase:
- Backend package paths and OpenAPI sources already renamed.

Output for next phase:
- `azents-public-client` and `azents-admin-client` packages exist for Python
  and TypeScript.
- Consumer imports can be updated in frontend phases.

Verification scope:
- OpenAPI dump/generate commands.
- Client package type checks where available.

## Phase 5: TypeScript apps and web UI rename

Branch: `codex/azents-rename-typescript-ui`

Purpose:
- Rename TypeScript apps/packages and product-visible UI text.
- Rename browser state keys, cookies, and `postMessage` event types.
- Rename Sentry project references and web/admin deployment package names.

Boundary:
- Includes `typescript/apps/azents-web`, `typescript/apps/azents-admin-web`,
  and `typescript/packages/azents-*`.
- Excludes Docker, ArgoCD, and Helm deployment rename unless required for local
  build config.
- Excludes durable data resources.

Input from previous phase:
- Generated Azents API clients.

Output for next phase:
- Web/admin apps build against renamed clients and show Azents branding.

Verification scope:
- `pnpm install` if lockfile changes require it.
- `pnpm run generate --filter` for affected clients.
- `pnpm run typecheck --filter` for affected apps/packages.
- `pnpm run lint --filter` for affected apps/packages.
- `pnpm run build --filter` for affected apps.

## Phase 6: Remove legacy Flutter app

Branch: `codex/azents-rename-dart`

Purpose:
- Remove the unmanaged legacy Flutter app instead of renaming it.

Boundary:
- Includes deleting `dart/azents-app`.
- Excludes backend and web code.

Input from previous phase:
- Azents domain and API naming contract.

Output for next phase:
- Legacy Flutter app sources are no longer part of the Azents rename surface.

Verification scope:
- Static scan confirms the legacy app path is gone.

## Phase 7: Non-durable infrastructure and CI rename

Branch: `codex/azents-rename-nondurable-infra`

Purpose:
- Rename deployment resources that do not own durable data.
- Rename Dockerfiles, ECR image names, GitHub Actions inputs/jobs/labels, ArgoCD
  apps, Kubernetes workload resources, Helm chart names/helpers, and DNS routing.

Boundary:
- Includes non-durable Kubernetes and CI/CD identifiers.
- Keeps RDS and object-storage endpoints pointing at existing Azents durable
  resources via `AZ_*` env names.
- Does not create Azents RDS/S3 durable replacements.
- Does not delete old Azents durable resources.

Input from previous phase:
- Code and app package names already use Azents.

Output for next phase:
- Azents workloads can be deployed while reading/writing old durable resources.

Verification scope:
- Docker build checks where feasible.
- `kustomize build` for all renamed ArgoCD apps.
- `helm template` and chart tests.
- Relevant Terragrunt plan for non-durable changes.

## Phase 8: Testenv, docs, and convention scope rename

Branch: `codex/azents-rename-testenv-docs`

Purpose:
- Rename test environment paths and project docs.
- Rename path-scoped convention scopes and regenerate convention indexes.

Boundary:
- Includes `testenv/azents`, `docs/azents`, `.claude/conventions/*azents*`,
  `.claude/rules/*azents*`, scripts and root guidance that refer to those
  paths.
- Does not change already implemented backend/frontend behavior except path
  references required by docs/testenv tooling.

Input from previous phase:
- Runtime, app, and infra names already use Azents.

Output for next phase:
- Test and documentation tooling targets Azents paths.

Verification scope:
- docs index generation.
- convention index generation.
- testenv preflight or focused tests where feasible.

## Phase 9: Verification on existing durable data

Branch: `codex/azents-rename-verification`

Purpose:
- Prove the renamed Azents stack works while still using existing Azents
  durable data resources.
- Record evidence and fix issues found during verification.

Boundary:
- Includes verification report and fixes required by failed checks.
- Excludes durable DB/S3 rename.

Input from previous phase:
- Full non-durable rename stack.

Output for next phase:
- Evidence that app behavior is ready for spec promotion and final data cutover.

Verification scope:
- Full command matrix listed below.
- Smoke/E2E checks for auth, OAuth, agent runtime create/resume, file
  upload/download, and Slack/Discord callbacks.

## Phase 10: Spec promotion and cutover runbook

Branch: `codex/azents-rename-spec-promotion`

Purpose:
- Run spec impact review.
- Mark design as implemented when verified.
- Update living specs and add ADR/cutover runbook entries as needed.
- Document the final durable data snapshot/restore and object-storage sync
  process.

Boundary:
- Includes spec/docs/runbook updates only.
- Does not execute production durable data cutover from the repo change itself.

Input from previous phase:
- Verification evidence.

Output for next phase:
- Specs and runbook reflect the renamed Azents system and the pending/final
  durable data cutover procedure.

Verification scope:
- `/spec-review` equivalent checks.
- docs/spec index checks.

## Phase 11: Cleanup

Branch: `codex/azents-rename-cleanup`

Purpose:
- Remove temporary phase plans after implementation is complete.
- Remove stale Azents references that were intentionally deferred.
- Keep only explicitly historical references if the spec-promotion phase
  allowlists them.

Boundary:
- Includes cleanup and final scans.
- Does not delete production durable data resources. That deletion follows the
  operational retention policy after final data cutover.

Input from previous phase:
- Promoted specs and runbook.

Output:
- Repo has no unintended Azents/NI leftovers.

Verification scope:
- Final repository scan.
- Full affected quality checks if cleanup touches executable code.

## E2E primary matrix

| Area | What to verify | Primary check | Evidence |
| --- | --- | --- | --- |
| Auth | Email/password login and token refresh use Azents env/config names | azents/azents E2E auth flow after rename | E2E logs and screenshots where applicable |
| OAuth | Slack, Discord, GitHub, MCP callback URLs use Azents domains and event names | Browser E2E or live callback smoke | callback request/response logs |
| Agent runtime | Runtime provider and runner connect with `AZ_RUNTIME_*` env vars | Runtime create/resume E2E | runtime provider logs and API state |
| Files | Upload/download uses Azents app code with old durable bucket before cutover | file exchange E2E | API response and object-storage evidence |
| Web UI | Product text, storage keys, cookies, and postMessage types are renamed | Browser E2E plus static scan | E2E logs and `rg` scan |
| Admin UI | Admin client imports and admin screens work after package rename | admin smoke/typecheck | typecheck/build logs |
| Testenv | renamed testenv path can start services and run targeted tests | testenv preflight/devserver check | command output |
| Infra render | Azents ArgoCD/Helm manifests render and point durable config to old resources before cutover | `kustomize build`, `helm template` | rendered manifest diff/log |

## Testenv fixture and prerequisite needs

- Browser/OAuth prerequisite snapshots must be renamed from Azents-specific env
  keys to Azents-specific env keys.
- Any live E2E GitHub Actions secrets using `AZENTS_*` must be renamed to
  `AZ_*`.
- Runtime provider readiness fixtures must include `AZ_RUNTIME_*` env names.
- Durable-data verification fixtures must explicitly record whether the stack is
  still using legacy Azents RDS/S3 endpoints or final Azents endpoints.

## Blockers and manual actions

- External service consoles must be updated before live OAuth verification:
  Slack, Discord, GitHub App, Sentry, and any OAuth provider callback allowlist.
- Production final data cutover requires a maintenance window and write freeze.
- RDS snapshot/restore and object-storage sync are operational actions, not
  normal code PR side effects.
- Old durable resource deletion must wait for the agreed retention period after
  successful cutover.
