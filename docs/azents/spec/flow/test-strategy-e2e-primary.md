---
title: "E2E Primary Test Strategy"
created: 2026-05-13
tags: [testenv, qa, e2e, process]
spec_type: flow
owner: "@Hardtack"
touches_domains: []
code_paths:
  - .claude/skills/feature-design/SKILL.md
  - .claude/skills/ship-feature/SKILL.md
  - .github/workflows/ci.yaml
  - .github/workflows/azents-live-e2e.yaml
  - docs/azents/AGENTS.md
  - testenv/azents/AGENTS.md
  - testenv/azents/README.md
  - testenv/azents/contracts/**
  - testenv/azents/e2e/**
  - testenv/azents/testenv/bootstrap_runner.py
  - testenv/azents/testenv/prerequisite_*.py
  - testenv/azents/testenv/checks/**
  - testenv/azents/testenv/live/**
  - python/apps/azents/src/azents/api/testenv/**
  - python/apps/azents/src/azents/runtime/**
  - python/apps/azents-runtime-provider-docker/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents-runtime-runner/**
last_verified_at: 2026-06-15
spec_version: 5
---

# E2E Primary Test Strategy

## Overview

azents product behavior verification uses E2E as primary layer. `testenv/azents` is not a runner wrapping E2E, but a support layer responsible for fixture readiness and prerequisite classification.

This spec defines boundaries connecting azents feature design, E2E location, fixture/prerequisite support, credential/prerequisite snapshot, and CI execution policy in current implementation.

## Layer Boundaries

| Layer | Responsibility | Prohibited |
| --- | --- | --- |
| `testenv/azents/e2e/` | pytest-based product behavior E2E. Primary verification location for API/WS/browser/user journey regression. | Do not wrap E2E with testenv fixture command. |
| `testenv/azents/fixtures/` | Prepare reusable product state readiness and verify with doctor. | Do not own E2E/feature QA plan instead. |
| `testenv/azents/contracts/` | Declare credential/prerequisite contract and safe metadata schema. | Do not output raw secrets or store them in snapshots. |
| `testenv/azents/support/` | Promote only helpers confirmed to be repeatedly used in E2E/fixture/prerequisite. | Do not preemptively commonize. |

Manual-only runbook, blocked placeholder, removed-feature residue check, legacy TC markdown, `run-tc`, verifier, and markdown bash fallback are not part of event azents verification path. Primary evidence for product behavior QA is E2E result, and it is not separated into long-term catalog files.

## Local Bootstrap and Fixture Flow

Event local preparation flow:

```bash
cd testenv/azents
uv run testenv bootstrap local
uv run testenv fixture doctor <fixture-id> --json
uv run testenv fixture up <fixture-id> --json
```

`bootstrap local` prepares only non-secret `.env` defaults, Docker compose infra, current-worktree devserver, `fixture up devserver`, and doctor summary. It does not create external secrets, log into Tailscale/OAuth, write directly to product DB, or run E2E. If fixture is missing/stale, prepare it explicitly with guidance from `fixture doctor` / `fixture up` / `fixture reset`.

## Credential and Prerequisite Snapshot

Credential and prerequisite are separated.

- **credential** — whether secret/source exists.
- **prerequisite** — whether credential, external service state, and local callback/config combine into test-runnable state.

Prepare phase runs doctor and stores snapshot.

```bash
cd testenv/azents
uv run testenv prerequisite prepare --profile live --json
```

Current priority contracts are Bedrock AWS shared credentials and Browser/OAuth storage state. Snapshot includes `generated_at`, `mode`, `max_age_seconds`, `contract_hash`, `worktree_fingerprint`, `env_fingerprint`, `status`, `checks`, and `guidance`. CLI output and snapshot record only safe metadata such as present/missing, profile, region, and source path; they do not include secret values.

Agent Runtime live prerequisite is declared with Runtime provider/control contract. Contract snapshot is stored around checks/guidance, and live helper separately calculates safe metadata such as provider mode, provider id, Kubernetes/Docker availability, Helm availability, and Runtime namespace. Provider credential, runtime-control auth token, and token map literal are not included in snapshot/API/E2E evidence.

Consumer policy:

| Consumer | Missing/stale snapshot |
| --- | --- |
| required E2E | fail |
| optional/live E2E | skip summary |
| fixture/prerequisite diagnostic | structured prerequisite error |
| prepare command | environment prep failure |

E2E and fixture/prerequisite diagnostic read only snapshot during test and do not run doctor again.

## CI Policy

Always-on deterministic CI does not depend on external credential.

- Python lint/type/unit and other deterministic checks.
- `uv run pytest -vv -m "not live_external" ./src` in `testenv/azents/e2e`.
- testenv fixture/prerequisite unit, contract lint.

Live/external verification runs only conditionally.

- PR label `azents-live-e2e`.
- manual workflow dispatch.
- nightly schedule.

Live workflow runs `live_external` E2E marker. If credential is missing in live verification requested by maintainer, treat as fail; in nightly optional verification, report prerequisite not-ready as skip summary and do not fail deterministic CI.

Agent Runtime Provider E2E follows same policy. In required live Runtime Provider run, missing/stale Runtime provider prerequisite is treated as fail. Optional/nightly run can report prerequisite-not-ready as skip summary, but deterministic CI continues to run provider helper/auth negative unit path and prerequisite contract lint with `-m "not live_external"`.

## Feature and Ship Workflow Requirements

azents feature design must include `## Test Strategy` section. Minimum items are E2E primary plan, whether testenv fixture/prerequisite support is needed and why, fixture/product seed, credential contract, prerequisite snapshot, evidence format, CI execution policy, and live/optional skip/fail criteria.

`ship-feature` phase plan includes E2E primary verification matrix. If product behavior verification remains only as testenv support without E2E, an explicit exception is required. QA report separates verification goal, E2E evidence, and fixture/prerequisite evidence.

External substrate features such as Agent Runtime Provider are recorded in two layers.

- deterministic evidence: auth negative matrix, redaction assertion, prerequisite contract lint, diagnostic API shape, no-active-provider helper behavior, explicit skip/fail reason of Helm render test.
- live evidence: provider-enabled lifecycle, Provider-reported workspace path, persistence preservation across stop/restart, reset-only destructive behavior, reconnect/stale generation, provider liveness, Helm-enabled environment participation.

Local/PR environment without live substrate does not fake live PASS. Instead, separate prerequisite snapshot state and deterministic evidence in PR body and design QA record. If primary E2E substrate such as Browser runner or Docker/testcontainers is unavailable and product path cannot be executed, do not replace it with PASS. Track scenario, blocker category, observed error, expected verification target, and next action in GitHub Issue, and leave blocked evidence plus issue link in design QA record.

## Related Records

- testenv operational guide: [`../../../testenv/azents/AGENTS.md`](../../../../testenv/azents/AGENTS.md)
