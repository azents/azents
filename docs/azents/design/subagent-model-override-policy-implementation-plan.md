---
title: "Subagent Model Override Policy Implementation Plan"
created: 2026-07-17
updated: 2026-07-17
tags: [agent, backend, frontend, engine, subagent, models, testing]
---

# Subagent Model Override Policy Implementation Plan

## Feature Summary

Implement the model-scoped explicit subagent override policy defined by [ADR-0165](../adr/0165-subagent-model-override-policy.md) and [Subagent Model Override Policy](subagent-model-override-policy.md).

Each selectable model option gains enabled-by-default explicit subagent availability and optional bounded guidance. The `spawn_agent` tool advertises and accepts only enabled explicit targets while preserving parent-profile inheritance.

## Stack

### PR 1 — Design

Base: `main`

- ADR-0165
- Feature design
- Initial impact and validation matrix

### PR 2 — Implementation plan

Base: PR 1

- This phased plan
- Explicit PR boundaries and dependency order
- Test and rollout expectations

### PR 3 — Backend policy and runtime

Base: PR 2

Data and API:

- Extend selectable model settings input/stored schemas.
- Normalize enabled and guidance defaults.
- Generate an Alembic revision that backfills Agent, Workspace, and Agent Session JSONB shapes.
- Regenerate public OpenAPI and Python/TypeScript clients.

Runtime:

- Filter the dynamic `spawn_agent` target list.
- Render bounded per-target guidance.
- Reject disabled explicit target labels before child creation.
- Preserve inherited and effort-only inherited spawning.

Tests:

- Core settings validation and normalization.
- Agent/Workspace persistence and API round trips.
- Migration upgrade coverage.
- Subagent description, validation, inheritance, and no-side-effect failure coverage.

### PR 4 — Model settings UI

Base: PR 3

- Add subagent availability and guidance to frontend form state and API mapping.
- Add a Subagents section to the per-model settings modal.
- Preserve policy when the physical model changes.
- Add localized utility copy in all supported locales.
- Add frontend unit coverage and Storybook interaction states.

### PR 5 — E2E validation

Base: PR 4

- Extend deterministic subagent/profile E2E coverage.
- Add required web-surface persistence coverage.
- Run the validation matrix and fix behavior drift discovered by E2E.
- Record validation evidence in the PR body rather than adding a permanent report document.

### PR 6 — Spec promotion

Base: PR 5

- Run spec review.
- Update Agent domain, Toolkit domain, and Agent execution-loop specs.
- Mark the feature design implemented after verification.
- Keep ADR-0165 unchanged after adoption.

### PR 7 — Cleanup

Base: PR 6

- Remove this temporary implementation plan.
- Retain ADR, implemented design, living specs, tests, and code as sources of truth.

## Dependencies

The stack is strictly ordered:

1. Backend types and generated clients must land before frontend consumption.
2. Frontend settings must exist before web-surface E2E.
3. Full E2E validation must complete before spec promotion.
4. Cleanup runs only after implementation and specs are complete.

No external service, live credential, or manual fixture preparation is required.

## Data and Rollout

The backend phase creates a new migration rather than modifying an executed migration. It materializes:

- `subagent_enabled = true`
- `subagent_guidance = null`

inside existing selectable model settings and active Session model-settings snapshots. The application then requires the complete stored shape without a legacy missing-field fallback.

The rollout preserves current behavior because every existing option remains eligible. No existing child Session is stopped or rerouted.

## E2E Primary Validation Matrix

| Behavior | API/runtime E2E | Web-surface E2E |
|---|---:|---:|
| Enabled target appears and can be selected | Required | — |
| Disabled explicit target is rejected without child creation | Required | — |
| Disabled parent target remains inheritable | Required | — |
| Effort-only override retains inherited target | Required | — |
| All explicit targets disabled still permits inheritance | Required | — |
| Guidance and enabled state persist on Agent settings | API assertion | Required |
| Workspace defaults copy policy to a new Agent | Required | Required where practical |
| Later policy change does not invalidate existing child follow-up | Required | — |

## Fixture and Prerequisite Support

Use the existing credential-free deterministic model-listing and mock provider substrate. No new external prerequisite snapshot is needed.

The web-surface test uses existing authenticated browser setup and normal public API/UI paths. It must not write directly to the database.

## Validation by Phase

### Backend phase

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pyright`
- Targeted and full backend pytest as practical
- OpenAPI/client generation consistency

### Frontend phase

- `pnpm run format:check`
- `pnpm run lint`
- `pnpm run typecheck`
- `pnpm --filter @azents/web test`
- Storybook interaction coverage

### E2E phase

- Targeted deterministic subagent/profile tests
- Targeted web-surface model-settings tests
- Required credential-free deterministic and web-surface CI lanes

### Spec and cleanup phases

- Spec review
- Docs index validation
- `git diff --check`

## Failure and Skip Policy

- Required deterministic and web-surface tests fail when the environment is ready but behavior is incorrect.
- No planned test is marked `live_external` or skipped for missing credentials.
- An unavailable local Docker environment may prevent local full E2E execution; CI remains required and must pass before completion.
- Any implementation/spec drift found during validation is fixed before spec promotion rather than documented as accepted drift.

## Spec Impact Candidates

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/domain/toolkit.md`
- `docs/azents/spec/flow/agent-execution-loop.md`

## Cleanup Notes

Delete this plan in PR 7. Do not delete ADR-0165 or the implemented design document. No compatibility shim or legacy option shape remains after migration.
