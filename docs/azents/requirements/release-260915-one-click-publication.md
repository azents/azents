---
title: "One-Click Public Release Requirements"
created: 2026-09-15
updated: 2026-09-15
implemented: 2026-09-15
tags: [release, github-actions, helm, open-source]
document_role: primary
document_type: requirements
snapshot_id: release-260915
---

# One-Click Public Release Requirements

- Snapshot: `release-260915`
- Document reference: `release-260915/REQ`

## Problem

Publishing an Azents public release currently requires a preparatory pull request that changes the Helm chart version before the protected release workflow can run. This separates version preparation from publication and prevents maintainers from completing a release through one intentional workflow invocation.

## Primary Context

### Primary System Outcome

A maintainer invokes the protected release workflow from `main` with a release version and channel, and that one invocation publishes consistently versioned images, an OCI Helm chart, a Git tag, and a GitHub Release without a prior chart-version change.

## Supporting Scenarios or Effects

- Repeated prerelease publication does not require source-only version bump pull requests.
- A failed or invalid release stops before publishing a mismatched Helm chart.
- The release commit remains unchanged by the publication workflow.

## Goals

- Make one protected workflow invocation the complete public release operation.
- Keep every published artifact aligned with the requested release version.
- Preserve the existing release permission, channel, tag, provenance, and publication safeguards.

## Non-Goals

- Making publication across GHCR, Git tags, and GitHub Releases transactionally atomic.
- Automatically changing GHCR package visibility.
- Deploying a published release to downstream environments.
- Committing generated release metadata back to `main`.

## Requirements

### REQ-1. Single-invocation publication

A maintainer must be able to publish an external release from `main` through one release workflow invocation without first changing the Helm chart version in source control.

**Acceptance criteria**

- The workflow requires only the release version and release channel inputs already exposed to maintainers.
- A valid invocation builds and publishes the existing release image matrix, the OCI Helm chart, the Git tag, and the GitHub Release.
- The workflow does not create or require a preparatory chart-version commit.

### REQ-2. Artifact version consistency

The published Helm chart version and application version must match the requested release version without its leading `v`.

**Acceptance criteria**

- `v0.1.0-alpha.1` produces chart `version` and `appVersion` values of `0.1.0-alpha.1`.
- The workflow validates the packaged chart metadata before pushing it.
- A metadata mismatch fails the chart publication job before the OCI push.

### REQ-3. Release-source integrity

The workflow must preserve the release commit as the source identity of every published artifact.

**Acceptance criteria**

- The workflow runs only from the `main` branch.
- Image labels and digests continue to identify the workflow commit.
- The Git tag continues to target the workflow commit.
- The workflow does not modify or push source files while publishing.

### REQ-4. Existing release safeguards

The one-click flow must retain the established validation and release-channel behavior.

**Acceptance criteria**

- Invalid SemVer input fails before artifact publication.
- Stable and prerelease channel/version mismatches fail before artifact publication.
- An existing tag fails validation.
- Prereleases continue to publish only the exact prerelease image tag.
- Stable releases continue to publish the exact, minor, major, and `latest` image tags.

## Fixed Constraints

- Public release publication remains protected by the `release` GitHub Environment.
- Release images continue to include provenance and SBOM attestations.
- The Helm chart remains published to the established GHCR OCI repository.
- Existing implemented Requirements and ADR records remain immutable.

## Open Assumptions

- Maintainers configure the `release` GitHub Environment and public package visibility outside this workflow.
- GitHub and GHCR may retain partial external state if a later publication step fails.

## Confirmation

Confirmed by the requester on 2026-09-15 before ADR and design decisions began.
