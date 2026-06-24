---
title: "ADR-0073: Open Source CI Policy"
created: 2026-06-23
tags: [ci-cd, github-actions, security, process]
---

# ADR-0073: Open Source CI Policy

## Context

Azents is becoming a public open-source repository. CI must therefore serve two goals at the same time:

- give contributors fast, deterministic feedback on pull requests,
- avoid exposing trusted infrastructure, secrets, write tokens, or private deployment systems to untrusted pull request code.

The release and snapshot artifact policy is recorded separately in [ADR-0072](0072-release-and-snapshot-artifact-policy.md). This ADR covers CI only: runner selection, required checks, path filtering, pull request safety, and workflow trigger boundaries. Snapshot publishing, external release creation, downstream deployment, and artifact retention remain governed by ADR-0072.

## Decision

### ADR-0073-D1 — Use GitHub-hosted runners only in the Azents repository

All Azents repository workflows use GitHub-hosted runners. The default Linux runner is `ubuntu-latest`.

Azents workflows do not use self-hosted runners. This applies to pull request CI, main branch CI, snapshot publishing, release publishing, and maintenance workflows in the public Azents repository.

Rationale:

- Public pull requests can contain untrusted code.
- Self-hosted runners increase the risk of exposing private networks, persistent runner state, host credentials, and infrastructure-specific capabilities.
- The current Azents CI target is deterministic and expected to fit within GitHub-hosted runner resources.
- Avoiding self-hosted runners keeps the public repository workflow model simple.

Downstream private deployment repositories may choose their own runner model. That is outside this repository's CI policy.

### ADR-0073-D2 — Keep pull request CI read-only and secret-free

Pull request CI runs on the `pull_request` event with minimal permissions:

```yaml
permissions:
  contents: read
```

Pull request CI must not receive repository secrets or inherited secrets. It must not request `id-token: write`, `packages: write`, `contents: write`, or downstream deployment credentials.

Pull request CI must not:

- publish container images,
- publish Helm charts,
- create tags or GitHub Releases,
- send downstream `repository_dispatch` events,
- assume cloud roles,
- use live provider credentials,
- run private deployment logic.

The purpose of pull request CI is to prove that deterministic checks pass, not to publish or deploy artifacts.

### ADR-0073-D3 — Do not use `pull_request_target` initially

Initial Azents GitHub Actions workflows do not use `pull_request_target`.

Rationale:

- `pull_request_target` runs in the base repository context and can access privileged tokens or secrets.
- It is easy to accidentally combine `pull_request_target` with checking out and executing untrusted pull request code.
- The current Azents CI design does not require metadata-only privileged pull request automation.

If a future workflow needs `pull_request_target`, it requires a separate design/ADR and must be metadata-only by default: no pull request head checkout, no dependency installation from the pull request, no test/build execution, strict actor allowlists when relevant, and minimal permissions.

### ADR-0073-D4 — Exclude live/external tests from the initial CI migration

Live/external credential tests are not part of the initial Azents GitHub Actions migration.

The initial CI does not include:

- cloud-provider live credential tests,
- OAuth/browser stored-state tests,
- scheduled live E2E,
- label-triggered live E2E,
- comment-triggered live E2E,
- private downstream deployment smoke tests.

Required CI includes deterministic tests only. Existing test markers such as `live_external` and `runtime_provider` are excluded from required CI runs because they require external credentials or runtime provider infrastructure beyond deterministic PR CI.

### ADR-0073-D5 — Make deterministic E2E a required check

Deterministic Azents E2E is a required CI check.

The E2E command should exclude live/external tests, for example:

```bash
cd testenv/azents/e2e
uv run pytest -vv -m "not live_external and not runtime_provider" ./src
```

If a marker represents a live or private-infrastructure dependency, it must be excluded or reclassified before becoming part of required CI. Deterministic E2E failures block merge.

### ADR-0073-D6 — Split CI into stable required gate checks

CI is split by responsibility instead of using one large job.

The required branch-protection checks are stable gate jobs:

- `ci-pre-commit`
- `ci-python`
- `ci-python-e2e`
- `ci-typescript`
- `ci-helm`
- `ci-docker-build`

Run jobs may have implementation-specific names such as `ci-python-run`, but branch protection requires only the stable gate jobs. This allows path-filtered run jobs to be skipped while the corresponding required gate still reports success or failure.

### ADR-0073-D7 — Use changes + gate jobs for path filtering

Required CI uses path filtering, but not at the workflow trigger level.

The CI workflow always starts for:

```yaml
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
```

It does not use workflow-level `paths` or `paths-ignore` for required CI, because skipped required workflows can leave branch protection checks pending.

A lightweight `changes` job computes affected scopes. Expensive run jobs execute only when their scope changed. Each required gate job runs with `if: always()` and evaluates the corresponding run job result:

- if the `changes` job fails, is cancelled, or is skipped, every gate fails,
- if the scope did not change, the gate succeeds,
- if the scope changed and the run job succeeded, the gate succeeds,
- if the scope changed and the run job failed, was cancelled, or did not run as expected, the gate fails.

Changes under `.github/workflows/**` force all CI scopes to run. The `changes` checkout uses full history so pull request diff calculation does not depend on a shallow clone.

### ADR-0073-D8 — Keep pre-commit as an always-run required check

`pre-commit` remains a required CI check and runs on every pull request and main CI run.

Rationale:

- contributors may forget or choose not to run local hooks,
- generated documentation indexes must not drift,
- generated convention indexes must not drift,
- whitespace, YAML/JSON, lock/spec drift, and other hook-managed consistency checks must be caught in CI.

The `ci-pre-commit` job is not path-filtered. It is always required.

Heavy language checks may be skipped inside the pre-commit job when equivalent dedicated CI jobs run them, but the pre-commit workflow itself must remain required.

### ADR-0073-D9 — Separate write-permission workflows from CI

Write-permission workflows are not part of pull request CI.

Snapshot publishing, release publishing, provenance/SBOM attestation, GHCR package writes, Helm chart publishing, Git tag creation, GitHub Release creation, and downstream deployment dispatch are handled by separate trusted workflows. They run only on trusted events such as `push` to `main`, `workflow_dispatch`, or the protected release workflow defined by ADR-0072.

Those workflows may request write permissions, but CI workflows remain read-only unless a narrow exception is separately designed.

## Required Check Scope

### `ci-pre-commit`

Always runs.

Covers hook-managed consistency such as:

- `CLAUDE.md` / `AGENTS.md` import/link consistency,
- Azents docs index generation and validation,
- convention index generation,
- merge-conflict and case-conflict checks,
- end-of-file and trailing-whitespace checks,
- JSON/YAML checks,
- UTF-8 BOM checks,
- lock/spec drift checks owned by pre-commit.

Dedicated language jobs may cover heavy ruff, pyright, TypeScript, and E2E checks to avoid duplicate work.

### `ci-python`

Runs when Python source, shared Python libraries, Python project config, generated Python API contract inputs, or relevant CI config changes.

Covers:

- Python formatting/linting,
- type checking,
- unit/integration tests for Python packages,
- OpenAPI dump drift for the Azents backend when relevant.

### `ci-python-e2e`

Runs when Azents backend, shared Python libraries, E2E substrate, Docker Compose support, runtime support, or relevant CI config changes.

Covers deterministic E2E only. It excludes `live_external` and `runtime_provider` tests.

### `ci-typescript`

Runs when TypeScript source, TypeScript package config, generated TypeScript API contract inputs, frontend Dockerfiles, or relevant CI config changes.

Covers:

- format check,
- lint,
- typecheck,
- generated client compatibility when relevant.

### `ci-helm`

Runs when the Azents Helm chart or relevant CI config changes.

Covers:

- Helm lint,
- Helm template/render checks,
- chart-specific tests.

### `ci-docker-build`

Runs when Dockerfiles, Docker build contexts, backend/frontend/runtime source, `.dockerignore`, or relevant CI config changes.

Covers Docker build checks only. Pull request CI does not push images.

## Considered Options

### Use self-hosted runners for heavy jobs

Rejected. The CI target is expected to fit on GitHub-hosted `ubuntu-latest`, and the public repository security model is simpler if self-hosted runners are completely excluded from this repository.

### Keep live/external E2E workflows

Rejected for the initial migration. These tests rely on credentials or external state and are not part of deterministic open-source CI.

### Use workflow-level path filters for required checks

Rejected. Required workflows skipped by path filters can leave branch protection waiting for a check that never reports. Required CI workflows must start consistently and use internal changes + gate jobs instead.

### Skip pre-commit in CI because dedicated jobs cover checks

Rejected. The purpose of the pre-commit CI job is to catch contributors who did not run local hooks and to enforce hook-owned generated file consistency.

### Use `pull_request_target` for automation convenience

Rejected initially. The repository does not need privileged pull request automation for the initial CI migration, and avoiding `pull_request_target` reduces the risk of accidentally executing untrusted code in a privileged context.

## Consequences

- Public pull request CI is easier to reason about: GitHub-hosted runner, read-only token, no secrets.
- CI may spend more GitHub-hosted runner time than a self-hosted or heavily optimized setup, but public repository safety and simplicity are prioritized.
- Deterministic E2E becomes a merge gate.
- Path filtering still saves expensive job time while preserving stable required check names.
- Live/external test coverage is intentionally not represented in initial branch protection.
- Snapshot and release workflows must be designed separately with explicit trusted-event permissions.
