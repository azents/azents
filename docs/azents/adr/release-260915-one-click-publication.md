---
title: "One-Click Public Release"
created: 2026-09-15
updated: 2026-09-15
tags: [release, github-actions, helm, architecture]
document_role: primary
document_type: adr
snapshot_id: release-260915
---

# One-Click Public Release ADR

- Snapshot: `release-260915`
- Document reference: `release-260915/ADR`
- Requirements: [release-260915/REQ](../requirements/release-260915-one-click-publication.md)

## Context

The established release policy makes the protected workflow the only supported external publication path, but it also requires a release pull request to change `Chart.yaml` before workflow dispatch. That preparatory commit conflicts with `release-260915/REQ-1`, while the published chart still needs to retain the version lockstep required by the existing artifact policy.

## Decision Map

### Fixed or derived outcomes

- The protected manual release workflow remains the external publication authority.
- Git and image tags retain a leading `v`; Helm `version` and `appVersion` omit it.
- The existing image matrix, channel behavior, provenance, SBOM, tag creation, and GitHub Release flow remain unchanged.
- Published source identity remains the workflow commit on `main`.

### Material technical decisions

- [x] `release-260915/ADR-D1` — Materialize Helm release metadata at package time instead of requiring or creating a source version commit.

### Product questions

- None.

### Agent-owned details

- Shell variable names, metadata assertion implementation, and test helper structure.

## Decisions

### release-260915/ADR-D1 — Materialize Helm release metadata at package time

The release workflow passes its validated version to Helm packaging as both the chart version and application version. It validates the resulting archive metadata before pushing the chart. `Chart.yaml` remains a development source file and is neither required to match every external release version nor modified by the workflow.

This decision supersedes only the statement in `and-260623/ADR-D6` that release pull requests update `Chart.yaml` before workflow execution. It retains that decision's published version lockstep and OCI location.

#### Reasons

- It satisfies [release-260915/REQ-1](../requirements/release-260915-one-click-publication.md#req-1-single-invocation-publication) without weakening artifact consistency.
- Helm natively supports package-time `version` and `appVersion` overrides.
- Avoiding workflow-authored commits keeps branch protection, source review, and release SHA identity straightforward.
- Inspecting the completed archive makes the published artifact, rather than mutable workspace state, the verified boundary.

#### Rejected options

- **Keep the preparatory version pull request:** rejected because it preserves the multi-step operator workflow that the requester removed.
- **Have the release workflow commit `Chart.yaml` to `main`:** rejected because publication would mutate protected source state and could separate the built SHA from the version commit.
- **Create a detached release-only commit:** rejected because the release tag would no longer identify the reviewed `main` commit directly.
- **Skip packaged metadata validation:** rejected because an incorrect or ignored override could publish a chart inconsistent with the requested version.

## Consequences

- Maintainers can publish successive alpha, beta, release-candidate, and stable versions without source-only chart version changes.
- The `Chart.yaml` values visible at a release tag may differ from the metadata in the released chart archive; the workflow input, Git tag, release notes, and packaged archive are the release-version authorities.
- Reproducing the chart from a release tag requires supplying the tag-derived version to the same Helm packaging command.
- Existing partial-publication recovery constraints remain unchanged.
