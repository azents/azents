---
title: "Workspace-Owned Runtime Profiles Validation Report"
created: 2026-07-31
document_role: supporting
document_type: supporting-validation-report
tags: [runtime, provider, workspace, profile, validation, migration, testenv]
---

# Workspace-Owned Runtime Profiles Validation Report

## Scope

This report validates the complete `runtime-260730` stacked implementation through
`feature/runtime-profiles-08-validation` against:

- `runtime-260730/REQ`;
- `runtime-260730/ADR`;
- `runtime-260730/DESIGN`;
- the Runtime Profile implementation and phase plans; and
- the current living specs that will be promoted in the next stacked PR.

The validation boundary includes replacement E2E, migration equivalence and final-schema
verification, Provider and shared-control tests, active-source authority absence, and a strict
implementation-versus-spec comparison. It does not mutate a live Kubernetes cluster or perform a
production rollout.

## Environment

- Date: 2026-07-31
- Python: 3.14.6
- E2E substrate: local Unix Docker socket, real Docker Runtime Provider container, real Runtime
  Runner container, PostgreSQL, Redis, deterministic model proxy, Public API, Admin API, Worker, and
  Runtime Control containers
- Migration substrate: PostgreSQL 17 Testcontainers database
- Kubernetes evidence: deterministic Provider resource/lifecycle tests using the Provider's typed
  Kubernetes API boundary; no connected Kubernetes cluster was required by the Phase 8 branch
  contract

## Result

**PASS.** The implemented replacement has one active Workspace-owned Runtime Profile authority.
The new integrated E2E proves creation-time precedence, exact binding, desired/applied evidence,
explicit recreation, fail-closed Provider loss, retained selection, and recovery through the real
Docker Provider. Migration tests prove deterministic legacy conversion, fail-closed malformed or
unavailable inputs, exact final-schema removal, and structural downgrade behavior.

No product behavior defect remained after the final validation run. Validation found and corrected
three test/removal issues:

1. The first E2E draft compared the public logical Provider ID with the durable Provider resource
   ID. Assertions now compare each identifier only with its corresponding Runtime or configuration
   field.
2. `DockerContainer.stop()` removes a Testcontainers container. Provider-loss simulation now uses
   the wrapped Docker SDK container's stop/start operations so identity, volumes, and logs remain
   available and fixture teardown removes the container exactly once.
3. Two empty legacy Runtime execution-policy package markers remained after their implementations
   were removed. The validation branch deletes those final active package artifacts.

No new hard-to-reverse decision was discovered, so no additional ADR is required.

## Integrated scenario matrix

| Scenario | Evidence | Result |
| --- | --- | --- |
| Agent created without an explicit Profile and without a Workspace default | Integrated Public API E2E asserts a stored null selection, unavailable projection, and `runtime_profile_unconfigured` | PASS |
| Workspace default selection | Integrated Public API E2E creates a default, then proves a newly created Agent stores that exact Profile | PASS |
| Explicit selection precedence | Integrated Public API E2E creates an Agent with a different explicit Profile and proves it wins over the Workspace default | PASS |
| Exact Provider and infrastructure binding | E2E distinguishes logical Provider ID from durable Provider resource ID and matches the exact infrastructure and Workspace Profile IDs | PASS |
| Authoritative desired propagation | E2E observes the selected Profile in the initial desired revision before physical Runtime creation | PASS |
| Applied-state evidence | E2E waits for `applied` plus `RUNNING`, then requires desired/applied ID and digest equality, exact Provider-reported digest, exact Runner-reported digest, Provider acknowledgement time, and Runtime observation time | PASS |
| Explicit scoped recreation | E2E creates a Profile recreation operation, requires one successful target, and waits for a different applied revision | PASS |
| Provider loss without substitution | E2E stops the exact Provider container without deleting it, waits for Profile unavailability, proves the Agent retains its selection, and requires restart to fail with `409` | PASS |
| Provider recovery | E2E restarts the same Provider container, waits for a new authenticated registration, and proves the selected Profile becomes available again | PASS |
| Kubernetes network narrowing | Runtime Profile domain tests prove restrictive composition and reject CIDR expansion; Kubernetes Provider tests prove NetworkPolicy-only adoption and deployment hard-cap enforcement | PASS |
| Kubernetes Pod/PVC lifecycle | Kubernetes Provider tests prove Profile resource rendering, stop/restart PVC preservation, reset destruction/recreation, DinD topology, and exact configuration evidence | PASS |
| Docker-native Profile lifecycle | Docker Provider tests prove typed Profile acceptance, recreation-required configuration changes, workspace preservation on restart, reset destruction, and exact evidence | PASS |
| Durable recreation concurrency and failure | Backend repository/service tests prove exact target/version snapshots, bounded global concurrency, peer-worker exclusion, stale/superseded skips, exact-generation completion, and terminal retry exhaustion | PASS |
| Legacy migration equivalence | Migration tests resolve the legacy global/Workspace/Agent hierarchy into the expected deduplicated infrastructure Profile, Workspace Profile, Agent selection, Runtime binding, and desired revision | PASS |
| Malformed or unavailable migration inputs | Migration tests require blocked revisions or explicit migration failure instead of fallback for malformed capability, missing capabilities, disabled/decommissioning Provider, and missing selected Provider | PASS |
| Final legacy schema absence | A dedicated migration test proves seven obsolete tables, three Runtime columns, and five enum types are absent after `aafb89c5904b`, while recreation dispatch evidence remains | PASS |

## Command evidence

| Command | Result |
| --- | --- |
| `cd testenv/azents/e2e && uv run ruff check . && uv run ruff format --check . && uv run pyright .` | PASS — 72 files formatted, 0 type errors |
| `cd testenv/azents/e2e && uv run pytest -vv -s <three existing focused Provider nodes> src/tests/azents/public/test_runtime_profiles.py::test_runtime_profile_precedence_applied_evidence_and_recreation` | PASS — 4 passed in 61.28 seconds |
| `cd python/apps/azents && uv run ruff check . && uv run ruff format --check . && uv run pyright` | PASS — 1,481 files formatted, 0 type errors |
| `cd python/apps/azents && uv run pytest -vv migration_tests` | PASS — 21 passed in 108.94 seconds |
| `cd python/apps/azents && uv run pytest -vv <Runtime Profile core, repository, resolution, reconciliation, lifecycle, recreation, and route suites>` | PASS — 98 passed in 21.62 seconds |
| `cd python/apps/azents-runtime-provider-docker && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -vv` | PASS — 23 passed, 0 type errors |
| `cd python/apps/azents-runtime-provider-kubernetes && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -vv` | PASS — 71 passed, 0 type errors |
| `cd python/libs/azents-runtime-control && uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest -vv` | PASS — 89 passed, 0 type errors |
| `git diff --check` | PASS |

The focused runtime-provider CI lane now includes the new Runtime Profile node ID and its path
filter. Required PR CI remains the remote confirmation of the same checked-in command.

## Authority and removal audit

### Active implementation

Repository searches excluding immutable development snapshots, plans, migration history, and
migration-only tests found no active:

- `RuntimeExecutionPolicy` service or repository;
- Runtime policy snapshot aggregate or persistence access;
- global Runtime execution Profile authority;
- Workspace Runtime execution policy or allowance authority;
- Agent Runtime execution settings or Provider override authority;
- legacy Apply product path;
- dedicated Runner configuration-update protocol authority; or
- obsolete Runtime execution-policy E2E file.

The only removed-contract reference in active test source is the canonical Provider contract
rejection test, which proves an `execution_policy` capability branch is invalid. Provider tests
whose names contain `configuration_update` exercise the current Provider-local classification of
an exact full Runtime configuration change; they do not expose a separate control protocol or
authority.

Generated Public API fields named `runtime_provider_id` belong to the raw Agent Runtime routing
projection. They are not an Agent Provider preference or a selection fallback. The Agent contract
uses nullable `runtime_profile_id`.

### Migration-only history

Legacy table, column, enum, and effective-policy interpretation remains only in Alembic revisions
and migration tests. This is the intentional one-way conversion boundary. Runtime code does not
import or consult that historical interpretation.

## Implementation versus current living specs

The implementation matches `runtime-260730`; the following current specs still describe the
superseded hierarchy and must be promoted before the snapshot is marked implemented:

| Spec | Drift found | Required promotion |
| --- | --- | --- |
| `docs/azents/spec/domain/agent.md` | Still exposes Agent `runtime_provider_id`, versioned execution intent, restrictive overrides, and explicit Apply | Replace with nullable Workspace Runtime Profile selection, creation-time explicit/default/unconfigured precedence, availability projection, and no Provider override or Apply |
| `docs/azents/spec/domain/workspace.md` | Still describes allowed global Profiles plus Workspace restrictions | Replace with Workspace-owned complete Runtime Profile catalog, exact Provider/infrastructure binding, optional creation-time default, restrictive-only network policy, lifecycle, and recreation |
| `docs/azents/spec/domain/runtime-provider.md` | Still describes current-versus-accepted contract authority, Admin acceptance, Provider selection defaults, policy snapshots, and execution-policy capability modules | Make the authenticated current valid advertisement authoritative, document Provider-owned typed infrastructure Profiles, exact Runtime Profile compatibility, Provider-global operational configuration separation, and scoped recreation |
| `docs/azents/spec/flow/agent-runtime-control.md` | Still references execution-policy generations, snapshots, mixed-policy convergence, and explicit Apply | Document full configuration envelopes, desired/applied revision separation, exact Provider acknowledgement plus matching ordinary Runner state, one reconciliation action, in-place NetworkPolicy adoption, and explicit recreation for physical replacement |
| `docs/azents/spec/flow/agent-runtime-persistence.md` | Still describes Agent/Platform Provider selection, lazy legacy binding, immutable policy snapshots, restrictive convergence, and Apply | Document exact Profile-derived routing, desired/applied configuration revision persistence, no legacy fallback, storage-preserving recreation, and migration-only historical conversion |

`docs/azents/spec/flow/test-strategy-e2e-primary.md` contains only generic uses of the phrase
“execution policy” for test execution policy and has no Runtime Profile product drift.

## Gaps and disposition

| Classification | Finding | Disposition |
| --- | --- | --- |
| Product implementation | No missing approved Runtime Profile behavior found in the validated stack | No change |
| Security/data preservation | No fallback, authority expansion, implicit recreation, or workspace/PVC deletion path found | No change |
| Validation substrate | No live Kubernetes cluster journey runs in the focused CI lane | Accepted Phase 8 boundary; typed Kubernetes Provider integration tests cover resource rendering, hard-cap composition, PVC lifecycle, DinD, evidence, and in-place adoption |
| Living specs | Five specs describe superseded authority | Required next stacked PR; do not mark the snapshot implemented before promotion |
| Temporary plans | Multi-phase and phase plans remain tracked | Required final cleanup PR after spec promotion |

## Promotion readiness

The implementation is ready for living-spec promotion. The next stacked PR must:

1. run the spec-review workflow against the complete stack;
2. update the five drifted living specs to the validated replacement;
3. add `implemented: 2026-07-31` to both the Requirements and Design snapshots;
4. preserve the accepted ADR unchanged; and
5. leave all implementation and phase plans in place until the final cleanup PR.
