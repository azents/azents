---
title: "Subagent Spawn Inference Profile Implementation Plan"
created: 2026-07-11
updated: 2026-07-11
tags: [plan, agent, backend, engine, subagent, testenv]
---

# Subagent Spawn Inference Profile Implementation Plan

## Feature Summary

Implement the spawn-time inference profile override contract defined in
`docs/azents/design/subagent-spawn-inference-profile.md` and ADR-0124. A default subagent continues
to inherit its concrete parent Run profile unless `spawn_agent` explicitly selects an Agent-owned
model target label or reasoning effort for a non-full-history fork. Physical model identity remains
outside the model-visible contract.

## Stack Prefix

`Subagent inference profiles`

## PR Boundaries

1. **Design** — accepted design, ADR-0124, and documentation index.
2. **Implementation plan** — this phased plan, validation matrix, prerequisites, and spec impact.
3. **Backend implementation** — persistence enum migration, profile derivation, dynamic tool schema,
   atomic spawn behavior, and focused backend tests.
4. **E2E validation** — deterministic fixture support, user-visible behavior coverage, validation
   evidence, and fixes discovered during validation.
5. **Spec promotion** — update living specs and mark the design implemented after verification.
6. **Cleanup** — remove this temporary implementation plan and its generated index entry.

Each branch is based on the preceding branch. Implementation and validation stay separate so the
core contract can be reviewed independently from fixture and end-to-end test expansion.

## Phase 1 — Design

- Record the label-only override boundary and full-history restriction in ADR-0124.
- Define model-visible Codex V2-aligned prompting, profile derivation, persistence, and lifecycle.
- Define backend, schema-leakage, and E2E verification requirements.

## Phase 2 — Implementation Plan

- Establish reviewable PR boundaries and dependencies.
- Identify deterministic fixture and migration prerequisites.
- Record the primary validation matrix and spec impact candidates.

## Phase 3 — Backend Implementation

### Data and persistence

- Add `spawn_override` to `InferenceProfileSource` and the PostgreSQL enum through a generated
  Alembic revision.
- Preserve existing `AgentRun` inference fields and `AgentSession` last-used profile fields as the
  storage contract; do not add parallel child-profile state.
- Store `parent_agent_run_id` for both inherited and overridden first child runs.

### Runtime and lifecycle

- Add optional `model_target_label` and `reasoning_effort` inputs to `SpawnAgentInput`.
- Derive the child profile from the concrete parent Run for all four override combinations.
- Reuse Agent-scoped target resolution, explicit effort validation, ADR-0123 effort ordering, and
  effective limit calculation.
- Reject overrides for `all` or omitted `fork_turns` before creating child records.
- Complete all static validation and profile derivation inside the spawn transaction before child
  creation, message append, commit, activity publication, or broker wake-up.
- Initialize the child session's last-used requested label and effort from the selected profile so
  later `followup_task` runs use normal session-last-used resolution.

### Model-visible schema

- Build the `spawn_agent` description dynamically from the current Agent snapshot.
- List every Agent-owned target label and supported explicit effort value.
- Match the approved Codex V2 inheritance and exceptional-override wording.
- Exclude integration, provider, physical model, display name, family, catalog, snapshot, context,
  and pricing metadata.

### Backend tests

- Cover the four derivation combinations and each effort transition branch.
- Cover exact rejection of unsupported explicit effort, unknown label, invalid fork selection, and
  incomplete parent provenance.
- Assert no repository mutation or wake-up occurs for static validation failures.
- Verify inherited versus overridden provenance, changed-target limits, last-used profile state,
  and later worker profile selection.
- Snapshot the dynamic tool description and assert that prohibited physical metadata is absent.

## Phase 4 — E2E Validation

- Add deterministic test catalog targets with different effort capabilities without relying on live
  provider metadata.
- Update exact tool-schema fixtures after confirming the generated description contains labels only.
- Exercise inheritance, all supported override shapes, effort normalization, invalid input rollback,
  fork restrictions, persisted provenance, Subagent Tree state, and follow-up reuse.
- Record the commands, environment, results, fixture validation, and implementation-to-spec drift in
  a dated validation report under `docs/azents/design/`.
- Fix defects found by validation in this PR when the fix is local; otherwise amend the responsible
  earlier branch and rebase the stack with the repository stacked-PR workflow.

## Phase 5 — Spec Promotion

- Run the spec-review workflow against the complete implementation and validation diff.
- Update the agent domain and execution-flow specs that own subagent spawn, inference profile
  selection, persistence provenance, and continuation behavior.
- Add or update `code_paths` and `last_verified_at` for all directly covered implementation paths.
- Add `implemented: 2026-07-11` to the feature design only after implementation and E2E validation
  are complete.
- Do not modify ADR-0124 after adoption; superseding decisions require a new ADR.

## Phase 6 — Cleanup

- Remove this implementation plan after the living specs and implemented design are current.
- Regenerate the documentation index.
- Keep behavior changes, refactors, and validation fixes out of the cleanup PR.

## Dependencies

- Phase 3 depends on the accepted design and this plan.
- Phase 4 depends on the complete Phase 3 contract and database migration.
- Phase 5 depends on successful backend and E2E validation.
- Phase 6 depends on spec promotion being complete.

No frontend product UI or generated API client is expected. If the expanded inference source enum is
found in a public OpenAPI schema, regenerate affected clients from the source schema in Phase 3 and
document the additional generated files in that PR.

## E2E Primary Validation Matrix

| Scenario | Fork selection | Expected profile result | Required residue/evidence |
| --- | --- | --- | --- |
| No override | `all` | Exact concrete parent Run profile | Child run source `parent_run`; parent link present |
| Target only | `none` | Selected label; effort normalized from parent resolved effort | Source `spawn_override`; changed effective limits |
| Effort only | bounded count | Parent resolved model; explicit effort exactly validated | Source `spawn_override`; requested effort saved |
| Target and effort | bounded count | Selected label and exact supported effort | Source `spawn_override`; child appears and runs |
| Unsupported effort | `none` | Validation error | No child participant, session, run, activity, or wake-up |
| Unknown label | `none` | Validation error | No child residue |
| Override with full history | `all` or omitted | Validation error | No child residue |
| Override with bounded context | `none` or positive count | Accepted | Forked context matches requested selection |
| Follow-up after override | existing child | Re-resolve saved label via session-last-used behavior | Later run source and resolved profile are persisted |
| Tool schema inspection | any | Labels and effort values only | No physical model or provider metadata |

## Fixture and Prerequisite Support

- Use deterministic Agent-owned labels whose backing catalog entries advertise different canonical
  effort sets. This is required to verify normalization without depending on live provider changes.
- Ensure the mock inference provider can distinguish parent and child calls while returning stable
  outputs for tree and persistence assertions.
- Update stored tool-schema fixtures only from actual generated schema output.
- No external credentials are required for the primary matrix. Optional live-provider checks may
  skip only when credentials or provider availability are absent; deterministic tests must fail on
  any behavioral mismatch.
- Database-backed tests require the generated enum migration to be applied before E2E execution.

## Validation Commands and Evidence

Phase 3 runs targeted Ruff, Pyright, and Pytest checks from `python/apps/azents`, migration/schema
validation, documentation index validation, and `git diff --check`.

Phase 4 runs the focused subagent and per-prompt inference-profile E2E modules from `testenv/azents/e2e`
plus fixture snapshot checks. The validation report records exact commands, environment constraints,
pass/fail counts, skipped live checks, parent/child persisted summaries, and the schema leakage
assertion result. CI remains authoritative when local container or runtime prerequisites are absent;
missing deterministic fixtures or migration support is a failure rather than a skip.

## Known Blockers and Rollout

No design blocker is known. Local E2E may require the repository Docker Compose stack and a runtime
provider; if unavailable, record the local limitation and rely on CI only after all deterministic
fixture prerequisites pass locally.

The nullable tool fields preserve existing calls. The enum migration needs no data backfill. Deploy
the migration with the backend before any run can persist `spawn_override`. The feature does not add
a compatibility alias, raw model selector, user-facing setting, or permanent physical snapshot pin.

## Spec Impact Candidates

- `docs/azents/spec/domain/agent.md`
- `docs/azents/spec/flow/agent-execution-loop.md`
- `docs/azents/spec/flow/agent-runtime-persistence.md`

Confirm the exact set during Phase 5 using the spec-review workflow.
