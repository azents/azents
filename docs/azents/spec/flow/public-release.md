---
title: "Public Release Publication"
created: 2026-09-15
tags: [release, github-actions, helm, open-source]
spec_type: flow
owner: "@Hardtack"
touches_domains: []
code_paths:
  - .github/workflows/release.yaml
  - infra/charts/azents/Chart.yaml
  - testenv/azents/e2e/src/support_tests/test_release_workflow.py
last_verified_at: 2026-09-18
spec_version: 3
---

# Public Release Publication

## Overview

The protected manual GitHub Actions Release workflow is the supported Azents public
publication authority. One invocation from `main` accepts a version and channel,
publishes the release image matrix and OCI Helm chart, creates the matching Git tag,
creates a GitHub Release, and can hand the completed release metadata to a configured
downstream deployment repository. Publication does not require or create a
preparatory source version commit. Azents does not own the downstream deployment
implementation.

The workflow uses the `release` GitHub Environment for validation, every image build,
chart publication, and final GitHub publication. Version-specific concurrency does
not cancel an in-progress release.

## Input and Source Validation

The workflow accepts:

- `version`: a leading-`v` semantic version such as `v0.1.0` or
  `v0.2.0-rc.1`;
- `channel`: `stable` or `prerelease`.

Validation requires the workflow ref to be `refs/heads/main`, rejects an invalid
version, rejects a stable channel with a prerelease version, rejects a prerelease
channel with a stable version, and rejects an already-existing Git ref for the
requested version. It derives the chart version by removing the leading `v` and
derives stable major and minor image tags from the core version.

Source `infra/charts/azents/Chart.yaml` metadata is development metadata, not the
published release-version authority. The workflow does not edit or push repository
files while publishing.

## Release Images

The release matrix builds and pushes these GHCR packages from the selected `main`
commit:

- `azents-server`;
- `azents-web`;
- `azents-admin-web`;
- `azents-runtime-runner`;
- `azents-runtime-proxy`;
- `azents-runtime-engine`;
- `azents-runtime-provider-kubernetes`;
- `azents-runtime-provider-docker`.

Every image receives the exact requested version tag, source/revision/version/created
labels, provenance, and an SBOM. A prerelease receives only its exact version tag. A
stable release additionally updates its `vMAJOR.MINOR`, `vMAJOR`, and `latest` tags.
Each matrix job records the pushed digest in a required metadata artifact for final
release notes.

## Helm Chart Publication

The chart job packages `infra/charts/azents` with the validated version supplied as
both Helm `version` and `appVersion`. It reads the completed archive metadata before
publication and requires both values to equal the validated version without the
leading `v`. A mismatch fails before `helm push`.

The verified archive is published to
`oci://ghcr.io/azents/charts/azents:<chart-version>`. The package-time overrides do
not mutate `Chart.yaml`.

## Tag and GitHub Release

The GitHub Release job starts only after validation, every image build, and chart
publication succeed. It downloads all image metadata, creates release notes listing
image tags and digests plus the OCI chart reference, and identifies provenance and
SBOM availability.

The workflow then creates and pushes the requested Git tag at the workflow commit.
It creates a GitHub Release only after verifying that tag; prerelease versions mark
the GitHub Release as a prerelease.

## Downstream Release Handoff

After the GitHub Release succeeds, a separate job checks the generic downstream
configuration:

- `DOWNSTREAM_DEPLOY_REPOSITORY` identifies the target repository;
- `DOWNSTREAM_DEPLOY_TOKEN` authorizes `repository_dispatch`;
- `DOWNSTREAM_RELEASE_EVENT_TYPE` optionally overrides the default
  `azents_release_published` event type.

When the repository or token is absent, the job reports a skip and leaves the
successful public release valid. When both are present, it downloads the completed
image metadata and dispatches a versioned payload containing the Azents repository,
`main` ref, immutable source commit SHA, workflow run ID, requested version and
channel, OCI chart reference and chart version, and every release image repository,
exact version tag, and digest. Image entries are sorted by component.

Azents does not encode downstream file paths, GitOps layout, cluster operations, pull
request behavior, or merge policy. A configured dispatch API failure fails the
handoff job visibly, but it cannot roll back artifacts that were already published.

## Failure and Recovery

Publication is not transactionally atomic across GHCR, the Git tag, and the GitHub
Release. A job failure before its external push publishes nothing from that job, but
a later failure can leave already-pushed images or a chart. An existing tag prevents
blind workflow replay for the same version. Operators must inspect and reconcile
partial external artifacts before completing or replacing a failed release.

The workflow never changes package visibility, deletes published artifacts, writes a
source commit, or directly invokes downstream deployment infrastructure.

## Verification

Required repository checks validate the workflow contract without publishing live
artifacts:

- explicit `main`-ref validation and absence of source-chart version lockstep;
- Helm `--version` and `--app-version` overrides;
- packaged metadata validation before the OCI push;
- release-note generation from the sorted metadata stream;
- post-publication downstream payload, configuration, skip, and dispatch contracts;
- workflow YAML and normal repository checks.

The first protected release invocation is the live end-to-end verification. Its
evidence is the workflow run, image digest artifacts, OCI chart metadata, Git tag,
and GitHub Release.

## Changelog

- **2026-09-18** (spec_version 3) — Named the GitHub Release job precisely after
  downstream dispatch became the post-publication final job.
- **2026-09-16** (spec_version 2) — Added the optional generic downstream release
  handoff after successful public publication.
- **2026-09-15** (spec_version 1) — Added the current protected one-invocation
  image, Helm chart, Git tag, and GitHub Release publication flow.
