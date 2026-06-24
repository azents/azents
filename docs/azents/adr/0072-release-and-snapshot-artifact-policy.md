---
title: "ADR-0072: Release and Snapshot Artifact Policy"
created: 2026-06-23
tags: [release, ci-cd, infra, security]
---

# ADR-0072: Release and Snapshot Artifact Policy

## Context

Azents is moving from a private SaaS-oriented deployment model to an open-source project that publishes user-facing artifacts. The previous single-branch automatic deployment model is not enough for an open-source ecosystem because it conflates three different concerns:

- public releases that external users may install and rely on,
- public release candidates that external users may test before a stable release,
- short-lived internal snapshots for active dogfooding and development-server deployment.

The build graph can remain shared, but the release identity, artifact visibility, retention, and deployment ownership must differ by channel.

This ADR records the release and CD artifact policy only. It intentionally does not decide the full GitHub Actions migration plan, PR CI policy, open-source contribution CI security model, or branch protection rules. Those remain follow-up design topics.

## Decision

### ADR-0072-D1 — Use three artifact channels

Azents uses three artifact channels:

- `stable` — external user-facing stable releases using SemVer tags such as `v0.1.0`.
- `prerelease` — external user-facing release candidates using SemVer prerelease tags such as `v0.2.0-rc.1` or `v0.2.0-beta.1`.
- `snapshot` — internal dogfooding artifacts using non-SemVer identifiers such as `dev-main-YYYYMMDD-<shortsha>`, `sha-<fullsha>`, and `run-<github_run_id>`.

Prerelease artifacts are external release candidates. Snapshot artifacts are internal deployment artifacts. They must not share SemVer identity or support expectations.

### ADR-0072-D2 — Separate public release packages from private snapshot packages

External stable and prerelease container images are published to public GHCR packages:

- `ghcr.io/azents/azents-server`
- `ghcr.io/azents/azents-web`
- `ghcr.io/azents/azents-admin-web`
- `ghcr.io/azents/azents-runtime-runner`
- `ghcr.io/azents/azents-runtime-provider-kubernetes`
- `ghcr.io/azents/azents-runtime-provider-docker`

Internal snapshot container images are published to separate private GHCR packages using the `-snapshot` suffix:

- `ghcr.io/azents/azents-server-snapshot`
- `ghcr.io/azents/azents-web-snapshot`
- `ghcr.io/azents/azents-admin-web-snapshot`
- `ghcr.io/azents/azents-runtime-runner-snapshot`
- `ghcr.io/azents/azents-runtime-provider-kubernetes-snapshot`
- `ghcr.io/azents/azents-runtime-provider-docker-snapshot`

Public release artifacts and fragile internal snapshots must not share the same GHCR package namespace.

### ADR-0072-D3 — Create external releases through a manual release workflow

External releases are created by a manual `release.yaml` workflow using `workflow_dispatch` inputs:

- `version` — `vX.Y.Z`, `vX.Y.Z-rc.N`, or `vX.Y.Z-beta.N`.
- `channel` — `stable` or `prerelease`.

Maintainers do not create release tags manually. The release workflow validates the version/channel, runs the required checks, builds and publishes release artifacts, creates the Git tag, and creates the GitHub Release.

The release workflow may require elevated permissions such as `contents: write`, `packages: write`, `id-token: write`, and `attestations: write`; it should be protected by a GitHub Environment such as `release` with maintainer approval.

### ADR-0072-D4 — Publish internal snapshots from Azents and delegate deployment to a generic downstream repository

Internal snapshots are created from `main` pushes and manual `workflow_dispatch` runs.

Azents owns:

- building snapshot images,
- publishing snapshot images,
- collecting image tag and digest metadata,
- sending a generic downstream `repository_dispatch` event.

The downstream deployment repository owns:

- GitOps values updates,
- ArgoCD or cluster synchronization,
- smoke tests,
- rollback behavior.

The initial downstream dispatch authentication uses a PAT. The workflow must be generic and configured via variables/secrets such as:

- `DOWNSTREAM_DEPLOY_REPOSITORY`
- `DOWNSTREAM_DEPLOY_TOKEN`
- `DOWNSTREAM_DEPLOY_EVENT_TYPE`

Azents workflows must not contain downstream-specific deployment paths, cluster logic, or private infrastructure assumptions. A future hardening step may replace PAT-based dispatch with a GitHub App installation token.

### ADR-0072-D5 — Use SemVer convenience tags for external releases and traceable tags for snapshots

Stable external releases publish these tags:

- `vX.Y.Z`
- `vX.Y`
- `vX`
- `latest`

Only stable releases update `latest`, `vX`, and `vX.Y`.

Prereleases publish only their exact prerelease tag, such as:

- `vX.Y.Z-rc.N`
- `vX.Y.Z-beta.N`

Prereleases do not update `latest`, `vX`, or `vX.Y`.

Internal snapshots publish:

- `dev-main-YYYYMMDD-<shortsha>`
- `sha-<fullsha>`
- `run-<github_run_id>`
- `dev-main` as an optional moving tag for manual debugging.

Automated downstream deployment must use the unique snapshot tag and digest from the dispatch payload. Tags are discovery and convenience identifiers; automated deployments prefer digest pinning whenever the digest is available.

### ADR-0072-D6 — Publish Helm charts only for external releases

The Helm chart is an external release artifact. External stable and prerelease releases publish the Azents chart to GHCR OCI:

```text
oci://ghcr.io/azents/charts/azents
```

Chart version and app version move in lockstep with the application release version without the leading `v`:

- Git/image tag: `v0.1.0`
- Chart `version`: `0.1.0`
- Chart `appVersion`: `"0.1.0"`
- OCI chart: `oci://ghcr.io/azents/charts/azents:0.1.0`

Prereleases use the same lockstep rule:

- Git/image tag: `v0.2.0-rc.1`
- Chart `version`: `0.2.0-rc.1`
- Chart `appVersion`: `"0.2.0-rc.1"`

Internal snapshots do not publish charts. Downstream deployments override image repository, tag, and digest using an existing chart.

Release PRs update `Chart.yaml` version and `appVersion` before the release workflow runs. The initial release workflow validates version consistency and does not auto-commit version bumps.

The chart must support digest pinning in image values so downstream snapshot deployments can render digest-pinned image references.

### ADR-0072-D7 — Keep external artifacts durable and clean up snapshots conservatively

External stable release artifacts are kept forever and are never automatic cleanup targets.

External prerelease artifacts are also kept forever initially. A future ADR may introduce prerelease cleanup if prerelease volume becomes operationally significant.

Internal snapshot packages use conservative initial cleanup:

- keep versions younger than 30 days,
- keep the last 30 package versions,
- keep the current `dev-main` target,
- never touch external release packages.

Future downstream-aware retention may tighten snapshot cleanup to:

- keep the currently deployed downstream digest,
- keep the previous successful deployed digest,
- keep the last 20 successful snapshots,
- keep the current `dev-main` target,
- delete non-protected snapshots older than 14 days.

Snapshot cleanup must never delete the currently deployed downstream digest once downstream deployment metadata is integrated.

### ADR-0072-D8 — Require provenance for all pushed images and SBOM for external releases

All pushed images across stable, prerelease, and snapshot channels must include:

- OCI labels,
- recorded image digest,
- provenance attestation.

OCI labels include at least:

- `org.opencontainers.image.source=https://github.com/azents/azents`
- `org.opencontainers.image.revision=<git sha>`
- `org.opencontainers.image.version=<release or snapshot version>`
- `org.opencontainers.image.created=<timestamp>`
- `org.opencontainers.image.title=<image name>`

External stable and prerelease images require SBOM attestation.

Internal snapshot images enable SBOM by default. If measured snapshot latency becomes unacceptable, snapshot SBOM may be moved to a non-blocking follow-up job or disabled for snapshots only. External release SBOM remains required.

### ADR-0072-D9 — Start public releases at v0.1.0 and defer v1.0 criteria

Azents uses SemVer for external releases. The first external release is `v0.1.0`.

`v0.x.y` releases are public previews. Breaking changes are allowed in `v0`, but release notes must explicitly call them out and provide migration guidance where practical.

`v1.0.0` readiness criteria are intentionally deferred. A future ADR will define the v1 stability contract before Azents is promoted to v1.

## Considered Options

### Use only stable and snapshot channels

Rejected. This omits a public release-candidate channel and encourages conflating internal snapshots with externally testable prereleases.

### Publish snapshots into the same GHCR packages as releases

Rejected. It mixes durable public releases with fragile internal development artifacts, makes package visibility impossible to separate, and complicates cleanup.

### Use tag-push releases

Rejected for the initial policy. Tag-push releases are common, but a manual release workflow can validate version/channel, chart version consistency, artifact publication, and GitHub Release creation before producing user-facing release state.

### Let Azents deploy downstream environments directly

Rejected. Deployment logic, GitOps paths, cluster synchronization, smoke tests, and rollback belong to the downstream deployment repository. Azents should publish artifacts and send metadata events only.

### Use polling instead of dispatch for internal dev deployment

Rejected for the initial dev deployment path because near-immediate dev deployment is required. Polling or scheduled reconciliation may be added later if dispatch proves unreliable.

### Publish a new Helm chart for every snapshot

Rejected. Snapshots are image artifacts, not chart releases. Downstream deployments can override image repository, tag, and digest using an existing chart.

### Make SBOM optional for snapshots from the start

Rejected. Snapshot SBOM is enabled by default so the artifact metadata model is consistent. It may be relaxed only after latency evidence shows that it materially harms snapshot deployment speed.

### Define v1.0 readiness now

Rejected. The current decision only establishes v0 public-preview semantics. v1 readiness should be decided in a future ADR when the public API, Helm contract, runtime protocol, migration policy, and self-host expectations are better understood.

## Consequences

- Public users see only stable and prerelease release artifacts in public GHCR packages.
- Internal snapshot artifacts remain private and short-lived.
- The release workflow becomes the only supported way to create external releases.
- Downstream dev deployment can happen immediately after snapshot publication without putting deployment logic in the public Azents repository.
- Snapshot cleanup starts conservative and can become downstream-aware later.
- All image-producing workflows need digest and provenance plumbing; external release workflows also need SBOM plumbing.
- The Helm chart must support digest pinning for downstream deployments.
- CI policy, branch protection, workflow migration sequencing, fork safety, and open-source contribution security remain unresolved follow-up design topics.
