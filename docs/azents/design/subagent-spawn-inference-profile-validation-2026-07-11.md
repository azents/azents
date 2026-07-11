---
title: "Subagent Spawn Inference Profile Validation Report"
created: 2026-07-11
updated: 2026-07-11
tags: [validation, agent, backend, engine, subagent, testenv]
---

# Subagent Spawn Inference Profile Validation Report

## Scope

Validate the implementation in `docs/azents/design/subagent-spawn-inference-profile.md`
against ADR-0124, the delivery plan, deterministic E2E fixtures, and current living specs.

## Environment

- Worktree runtime: Python 3.14
- Deterministic inference: Aimock fixture plus testenv model-listing catalog
- Catalog targets:
  - `Quality` resolves to the deterministic full reasoning target and supports `low`, `high`.
  - `Fast` resolves to the deterministic lightweight target and advertises no explicit effort.
- Local Docker socket: unavailable in the Agent runtime
- CI E2E: authoritative for container-backed execution

## Commands and Results

| Command | Result |
| --- | --- |
| `cd python/apps/azents && uv run ruff check ...` | Passed |
| `cd python/apps/azents && uv run pyright` | Passed, 0 errors |
| `cd python/apps/azents && uv run pytest -q` | Passed, 1189 tests; 366 skipped fixture-dependent tests |
| Focused backend profile/subagent/repository tests | Passed, 73 tests; 17 skipped without PostgreSQL fixture |
| `cd python/libs/azents-public-client && uv run pytest -q` | Passed, 421 tests |
| `cd typescript && pnpm run typecheck --filter=@azents/public-client` | Passed |
| `cd testenv/azents/e2e && uv run pyright` | Passed, 0 errors |
| Aimock fixture JSON parse | Passed |
| Focused container-backed E2E module | Blocked locally before test execution because `/var/run/docker.sock` is unavailable; CI result pending |

## E2E Matrix

| Scenario | Deterministic assertion | Coverage |
| --- | --- | --- |
| Concrete parent inheritance | Existing child-spawn E2E plus backend provenance assertions | Existing E2E and Phase 3 unit coverage |
| Target-only override | Parent `Quality/high` spawns `Fast`; effort normalizes to model Default | Added E2E |
| Explicit effort and target validation | Supported and unsupported effort paths | Existing per-prompt E2E and Phase 3 unit coverage |
| Full-history override | Tool error and no `invalid_history` tree node | Added E2E |
| Unknown target | Tool error and no `invalid_target` tree node | Added E2E |
| Bounded/none fork acceptance | `fork_turns = none` override creates and completes child | Added E2E; bounded count covered by unit tests |
| Follow-up continuity | Later child run requests `Fast` from `session_last_used` | Added E2E |
| Label-only schema | Labels/efforts present; integration and physical identity absent | Phase 3 schema unit coverage |
| Durable provenance | First child source is `spawn_override`; resolved target is deterministic `Fast` target | Added E2E |

## Fixture Validation

The existing deterministic model-listing fixture already provides two Agent-owned labels with
different effort capabilities, so no external credentials or new prerequisite snapshot is required.
The Aimock fixture adds root spawn, child completion, follow-up, full-history rejection, and unknown
label rejection turns. All fixture additions are selected by unique user-message or tool-call IDs.

## Implementation-to-Spec Comparison

| Implemented behavior | Current spec status before promotion |
| --- | --- |
| Spawn accepts optional Agent-owned target label and effort | Missing from current living specs |
| Full-history forks reject profile overrides | Missing from current living specs |
| First child run stores `spawn_override` and parent run link | Missing from current living specs |
| Later child runs use session-last-used target intent | General session precedence exists; subagent continuation is not explicit |
| Dynamic schema lists labels without physical model identity | Missing from current living specs |
| Static validation creates no child/session/run residue | Existing atomic spawn behavior is incomplete for this new boundary |

Phase 5 must promote these rows into the agent domain and execution/persistence flow specs after CI
confirms the deterministic E2E.

## CI Completion

Pending. Update this section with the Phase 4 PR CI run and focused E2E outcome before spec
promotion.
