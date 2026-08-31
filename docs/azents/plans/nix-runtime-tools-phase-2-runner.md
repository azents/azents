---
title: "Persistent Runtime System Tools Phase 2 Runner Plan"
created: 2026-08-31
tags: [runtime, package-management, nix, runner, prompt, implementation]
---

# Persistent Runtime System Tools Phase 2 Runner Plan

## Phase Execution Plan

- Phase: `2/4 — Runner Nix release and Agent interface`
- Branch/base: `feature/nix-runtime-tools-2-runner` → `feature/nix-runtime-tools-1-providers`
- PR boundary: Release-owned Nix seed artifacts, pre-registration bootstrap/reconciliation, protected Agent shell environment, exact Runtime Toolkit guidance, and focused Runner/Server tests
- Inputs: Confirmed `runtime-260831/REQ` and `nix-260831/REQ`; accepted `runtime-260831/ADR-D1`–`ADR-D5` with only the enforcement and exclusive-authority portions of `ADR-D3` and `ADR-D4` superseded by `nix-260831/ADR-D1`; approved `runtime-260831/DESIGN` revision `1` and `nix-260831/DESIGN` revision `1`; Phase 1 `/nix` mount contract in PR `#1584`
- Deliverables: The bundled Runner initializes or reconciles a persistent direct single-user Nix store before registration, exposes native Nix search/profile commands and Agent-overridable release defaults, keeps default user configuration and package state outside Workspace, preserves Agent-installed profile roots across release updates, and renders the approved package guidance only with the Runtime Toolkit
- Non-goals: Provider storage changes, Runtime capability/Profile/API/Admin configuration, package wrapper or policy commands, daemon/sidecar, package inventory, Kubernetes E2E substrate, Docker full E2E, Living Spec promotion
- Interfaces: Image seed root outside `/nix`; verified seed manifest; empty-store snapshot; existing-store NAR export; managed release profile; Agent package profile; pinned initial `nixpkgs` registry; conservative release defaults; Agent config/state/cache under `/nix`; Agent PATH; exact 30-word prompt block
- Approved Design mechanisms: `runtime-260831/M1`, `M7`, `M8`, `M9`; `nix-260831/M1`–`M5`
- Authority references: `runtime-260831/REQ-1`, `REQ-2`, `REQ-4`, `REQ-5`, `REQ-6`, `REQ-7`, `REQ-8`; `nix-260831/REQ-1`, `REQ-2`, `REQ-3`; `nix-260831/ADR-D1`
- Design delta: `None`
- Removal obligations: Replace the generic package-installation prompt claim with the exact native Nix guidance while retaining preinstalled tools and the Project dependency-manager boundary
- Absence verification: Searches and diffs prove no Nix capability/Profile field, database/API state, Provider catalog configuration, daemon/sidecar, package-policy service, custom package wrapper, or Workspace-backed default Nix state is introduced

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Runner release seed | `/root` | `python/apps/azents-runtime-runner/Dockerfile`, `docker/**` | Pinned Nix 2.35.2 image, pinned Nixpkgs revision, trusted cache key | Verified seed manifest, empty-store snapshot, release export, registry/config artifacts outside `/nix` | Docker build, artifact inspection, immutable reference checks |
| Bootstrap and environment | `/root` | `python/apps/azents-runtime-runner/src/**`, focused tests | Phase 1 writable `/nix`; release seed | Locked idempotent empty/existing-store bootstrap before registration; protected Nix environment and profile PATH | Ruff, ty, Runner pytest, focused bootstrap integration |
| Runtime prompt | `/root` | `python/apps/azents/src/azents/engine/tools/builtin.py`, focused tests | Existing Runtime Toolkit projection | Exact approved native CLI guidance with Runtime-free/shell-disabled absence | Ruff, ty, focused Server pytest |
| Active plan checkpoint | `/root` | `docs/azents/plans/nix-runtime-tools-phase-2-runner.md`, implementation plan | Stable phase diff | Evidence, scope-drift, remaining validation scope, risks | Docs validation, diff review |

- Integration order: inspect pinned Nix image → build deterministic seed artifacts → implement bootstrap state machine and environment → call bootstrap before Runner registration → add exact prompt → run Runner and Server validation → build and exercise the real Runner image
- Independent review: `hardtack`; review both approved snapshots, this plan, the complete Phase 2 diff, seed and bootstrap integrity, conservative release defaults, native Agent override authority, Nix-specific environment isolation, prompt exactness, and focused evidence
- Final validation: Runner Ruff/format/ty/pytest, focused and affected Server Ruff/format/ty/pytest, seed manifest integrity checks, real Runner image build, empty-store bootstrap, existing-store reconciliation, command availability, offline catalog availability, digest/corrupt-store failure tests, docs validation, `git diff --check`
- Scope-drift check: Approved persistent addon behavior and Agent-overridable default authority are present; no Provider lifecycle change, E2E substrate, product configuration, package inventory, wrapper, daemon, policy service, compatibility fallback, or unrelated dependency update is introduced
- Context checkpoint: Record release artifact identities, bootstrap generations and transaction boundaries, profile/environment contracts, prompt evidence, validation commands, remaining Phase 3 assumptions, risks, and blockers before PR creation

## Context Checkpoint

- Status: The superseding `nix-260831` snapshot resolves the feasibility conflict. Implementation, owner validation, complete independent review, and targeted re-review are complete; Phase 2 is ready for commit and PR.
- Completed mechanisms: `runtime-260831/M1`, `M7`, `M8`, and `M9` plus `nix-260831/M1`–`M5` are implemented with `Design delta: None`.
- Release artifacts: the Runner image pins Nix `2.35.2` and Nixpkgs revision `c5c4a43b0e8056328ec4529f735cabdb8f1942bb`. Generation `nix-2.35.2-nixpkgs-c5c4a43b0e8056328ec4529f735cabdb8f1942bb` contains a verified empty-store snapshot, release export, registry, Nix configuration, and manifest outside `/nix`.
- Bootstrap transaction: startup verifies all artifact digests, acquires `/nix/var/azents/bootstrap.lock`, completes empty-store staging before exposure, imports release paths into existing stores, validates the next release closure before atomically advancing managed roots, and records incomplete or complete generation state. Interrupted initial bootstrap may clear only the unexposed initial store; reconciliation never clears Agent-installed store paths or profiles.
- Environment interface: Agent commands receive default `/nix` store, log, native `NIX_CACHE_HOME`, `NIX_CONFIG_HOME`, `NIX_STATE_HOME`, Agent profile, release profile, TLS, and PATH variables. Global `XDG_*_HOME` variables remain untouched for non-Nix CLIs. Operation-level environment cannot accidentally replace the Runner defaults, while the Agent remains free to use native shell-local Nix configuration and command options. Default Nix addon state remains outside the Runner-reported Agent Workspace.
- Addon default authority: runtime defaults contain `require-sigs=true`, `fallback=false`, `builders =`, and `max-jobs=0`, and `nix copy --no-check-sigs` remains seed-build-only. Under `nix-260831/ADR-D1`, these are conservative release defaults rather than enforced policy. Agent-selected registries, options, local realization, and alternate trust settings remain ordinary Runtime shell behavior.
- Prompt evidence: the Runtime Toolkit adds the approved exact 30-word native Nix guidance and removes the generic package-installation claim. Shell-disabled Runtime Toolkit projection remains disabled, and no capability, Profile, API, database, Admin, or package-inventory surface is introduced.
- Validation evidence:
  - Runner: Ruff, formatter, `ty check --error-on-warning`, and `205 passed`.
  - Server: Ruff, formatter, `ty check --error-on-warning`, and `4,858 passed`.
  - Documentation: generated index check and `git diff --check` passed.
  - Image: the latest local build succeeded as `sha256:dddcf53fd82bddfb1c970647d80c568aa10c115bd06322be503fcb9d02d485f4`, size `1,023,314,166` bytes.
  - Empty store: UID/GID 1000 bootstrap succeeded without network; Nix `2.35.2`, pinned offline catalog search, release/catalog roots, `fallback=false`, `max-jobs=0`, and `require-sigs=true` were observed.
  - Persistence: signed-cache `hello` installation succeeded; a network-disabled reconciliation with a bumped seed generation retained the native Agent profile, executed `hello`, and retained offline catalog search. State recorded the original generation as `previous_generation`.
  - User configuration: native `nix registry add` uses `NIX_CONFIG_HOME=/nix/var/config/azents-agent`; a network-disabled replacement container retained the user registry while global `XDG_*_HOME` variables and `/home/agent/.config/nix/registry.json` remained untouched.
  - Corruption: `nix store verify --recursive --no-trust` passes the intact release/catalog closure and rejects a modified pinned catalog before Runner readiness.
  - Authority evidence: under `--network none`, native `nix build --option max-jobs 1 --option sandbox false` successfully built a local derivation, confirming the approved `nix-260831/ADR-D1` model that release settings are Agent-overridable defaults.
  - Review: exact reviewer `hardtack` closed the corrupt-store readiness and prompt-convention findings after targeted re-review. A final complete review against `nix-260831` remains.
- Scope and removal evidence: no Provider lifecycle change, Kubernetes or Docker E2E substrate, Azents-owned source-build workflow, daemon/sidecar, wrapper command, Workspace-backed default Nix state, compatibility fallback, Runtime configuration field, migration, OpenAPI change, or generated-client change is present. Native Agent-selected local realization remains ordinary addon behavior under `nix-260831/ADR-D1`. The generic prompt claim is replaced at its approved Phase 2 boundary.
- Remaining stack: complete environment validation and independent review, then commit and open the Phase 2 PR. Phase 3 owns Kubernetes product E2E and targeted Docker parity; Phase 4 owns Spec promotion and plan cleanup.
- Risks: Agent customization can reduce reproducibility, change package trust, or enable expensive local builds, but remains bounded by the existing Runtime sandbox and is not an Azents-managed policy violation. The image-local seed adds approximately 288 MiB of compressed artifacts, and broad default package cache coverage remains a later validation concern.
