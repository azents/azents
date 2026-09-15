---
title: "One-Click Public Release Design"
created: 2026-09-15
updated: 2026-09-15
implemented: 2026-09-15
tags: [release, github-actions, helm, design]
document_role: primary
document_type: design
snapshot_id: release-260915
---

# One-Click Public Release Design

- Snapshot: `release-260915`
- Document reference: `release-260915/DESIGN`
- Requirements: [release-260915/REQ](../requirements/release-260915-one-click-publication.md)
- ADR: [release-260915/ADR](../adr/release-260915-one-click-publication.md)

## Current Behavior and Gap

The manual release workflow validates version and channel inputs, rejects an existing tag, builds the release image matrix, packages the Helm chart, publishes artifacts, creates a Git tag, and creates a GitHub Release. Its validation additionally requires source `Chart.yaml` metadata to equal the requested version, so every release needs a preparatory source change.

The requested flow removes that preparatory step while preserving published version lockstep and release-source integrity.

## Requirements and ADR Traceability

| Requirement | Design mechanisms | ADR authority |
| --- | --- | --- |
| `release-260915/REQ-1` | M1, M2, M4 | D1 |
| `release-260915/REQ-2` | M1, M2, M3 | D1 |
| `release-260915/REQ-3` | M1, M2, M4 | D1 and existing release policy |
| `release-260915/REQ-4` | M1, M4 | Existing release policy |

## M1. Input and source validation

The validation job retains SemVer validation, stable/prerelease agreement, existing-tag rejection, and release output derivation. It adds an explicit `refs/heads/main` requirement so repository environment configuration is not the only defense against dispatching a release from another ref.

Source `Chart.yaml` version equality is removed from this job. The validated version without its leading `v` remains the sole chart-version output.

## M2. Package-time chart metadata

The chart publication job supplies the validated chart version to `helm package` through both `--version` and `--app-version`. It packages from the checked-out release commit without editing the source directory.

The expected archive path continues to be derived from the validated chart version and is the exact path pushed to the established GHCR OCI repository.

## M3. Packaged artifact validation

Before OCI publication, the workflow reads the completed archive metadata with Helm and extracts `version` and `appVersion`. Both values must exactly equal the validated chart version. A mismatch exits the job before `helm push`.

This validation boundary detects an ignored override, an unexpected Helm behavior change, or archive-path inconsistency without depending on repository mutations.

## M4. Preserved publication lifecycle

Image builds, tags, provenance, SBOM, metadata upload, chart push, release-note generation, Git tag creation, and GitHub Release creation retain their existing order and permissions. The workflow does not add commits, deployment behavior, package visibility changes, or compatibility fallback.

Failures before a registry push publish nothing from that job. Failures after an external push retain the existing operator recovery requirement to inspect and reconcile partial artifacts before retrying.

## Security and Permissions

- The workflow retains its `release` Environment boundary and existing write permissions.
- The explicit main-ref validation fails before image and chart jobs become eligible.
- No new secret, token, action, package manager, or external integration is introduced.
- The workflow never writes to the checked-out repository or protected branch.

## Migration, Rollout, and Recovery

The change applies to the next release workflow invocation after merge. No repository data, persistent application state, API, or deployment migration is required.

For a failed publication, maintainers use the existing version-specific concurrency and tag checks. If the chart was pushed but the final tag or GitHub Release failed, maintainers must inspect the external artifacts before deciding whether to complete or replace that version; the workflow does not overwrite an existing Git tag.

Rollback is a workflow-file revert. Previously published artifacts are immutable external state and are not deleted by rollback.

## Test Strategy

### Primary verification matrix

| Behavior | Verification |
| --- | --- |
| Source chart version no longer gates release input | Support contract test asserts the lockstep source-validation block is absent |
| Releases run only from main | Support contract test asserts explicit main-ref validation |
| Helm receives both release metadata overrides | Support contract test asserts `--version` and `--app-version` use the validated output |
| Packaged metadata is checked before push | Support contract test verifies step order and exact version/appVersion assertions |
| A representative alpha is packaged correctly | Local Helm package execution with `0.1.0-alpha.1`, followed by archive metadata inspection |
| Workflow remains valid YAML | Pre-commit YAML validation |

### E2E plan

A full publication E2E would create durable public packages, tags, and releases and therefore is not run in pull request CI. The first protected prerelease execution after merge is the operational end-to-end verification. Its evidence is the workflow run, image digest metadata, OCI chart metadata, Git tag, and GitHub prerelease.

### Testenv support

The existing Docker-free support-test job is sufficient because the regression surface is workflow text and command ordering. No fixture, browser, Runtime Provider, credential snapshot, or live external prerequisite is required in pull request CI.

### CI policy and skip criteria

The support tests and pre-commit checks are required. The live release execution is intentionally skipped in pull request CI and must not be simulated with alternate registries or credentials because that would not verify the protected publication boundary.

## Feasibility

- `helm package` exposes supported `--version` and `--app-version` flags.
- `helm show chart` reads metadata from the packaged archive before publication.
- The current workflow already carries the normalized chart version between jobs.
- No downstream interface consumes source `Chart.yaml` as the release-version authority.

All requirements are feasible with the current workflow and Helm toolchain.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Validate release inputs and require the `main` ref without source chart lockstep | `release-260915/REQ-1`, `release-260915/REQ-3`, `release-260915/REQ-4` | `required` |
| M2 | Materialize chart version and appVersion during Helm packaging | `release-260915/ADR-D1` | `decided` |
| M3 | Validate packaged chart metadata before OCI push | `release-260915/REQ-2`, `release-260915/ADR-D1` | `derived` |
| M4 | Preserve the existing publication lifecycle without source mutation | `release-260915/REQ-1`, `release-260915/REQ-3`, `release-260915/REQ-4` | `required` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Source `Chart.yaml` version/appVersion equality validation | `release-260915/REQ-1`, `release-260915/ADR-D1` | M2 and M3 | Release validation shell block | Contract test confirms the source parsing and equality error are absent |
| Required preparatory chart-version pull request | `release-260915/REQ-1`, `release-260915/ADR-D1` | One protected workflow invocation | Release operating procedure | Workflow accepts a representative alpha while source metadata remains unchanged |
| Other release validation and publication behavior | None | Existing release policy and M4 | Not removed | Contract tests and diff review confirm preservation |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-09-15`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4`
- Approved scope: One protected `main` workflow invocation derives and validates Helm release metadata and publishes the existing release artifact set without a preparatory source version change.
