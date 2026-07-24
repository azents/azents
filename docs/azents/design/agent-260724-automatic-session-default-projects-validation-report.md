---
title: "Automatic Session Default Projects Validation Report"
created: 2026-07-24
tags: [agent, session, workspace, project, validation, e2e, documentation]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: agent-260724
migration_source: "docs/azents/design/agent-260724-automatic-session-default-projects.md"
---

# Automatic Session Default Projects — Phase 5 Validation Report

## Scope and evidence policy

This report validates the `agent-260724` implementation through PR 6 (`feat/agent-default-projects-web`) against the confirmed Requirements, ADR, Design, and Phase 5 plan. It records executable evidence by source:

- **Local** — executed in the current worktree.
- **CI** — executed by GitHub Actions on the stacked PR commit.
- **Static/collection** — source inspection, test collection, generated-contract comparison, or quality checks that do not execute Docker-backed product journeys.
- **Unavailable** — attempted evidence blocked by the local substrate; it is not classified as a product failure.

Living specs were compared read-only. No spec, Requirements, ADR, or primary Design document was changed in this phase.

## Environment

- Worktree: `/workspace/agent/.azents/worktrees/prize-shock-curtain/azents`
- Validation branch: `feat/agent-default-projects-validation`
- Implementation base: `feat/agent-default-projects-web` (PR #852)
- Date: 2026-07-24 (KST)
- Local Docker prerequisite: **unavailable**. `test -S /var/run/docker.sock` returned `docker-socket-absent` (exit 1). Testcontainers consequently failed while creating its Docker network with `docker.errors.DockerException` wrapping `FileNotFoundError(2, 'No such file or directory')`.
- No live-provider credentials were used. External Channel scenarios use the repository fake Slack provider and deterministic test credentials only. Feature-specific policy/runtime behavior is exercised through Public API and Runtime boundaries; UI behavior is covered by existing `azents-web` unit/component tests, build, Storybook, and the repository Web Surface regression lane.

## Commands and results

### Backend and contract checks

| Command | Result | Evidence |
|---|---|---|
| `cd python/apps/azents && uv run ruff check .` | PASS | Local; all checks passed |
| `cd python/apps/azents && uv run ruff format --check .` | PASS | Local; 1,288 files formatted |
| `cd python/apps/azents && uv run pyright .` | PASS | Local; 0 errors/warnings/informations |
| Focused automatic-project/root-session/chat tests | PASS/expected skips | Local handoff evidence: `1 passed, 34 skipped`; skips require Docker-backed fixtures |
| Full backend pytest | PASS | Phase implementation handoff evidence: `2,390 passed, 561 skipped`; Docker-dependent tests are skipped by the documented substrate policy |
| `uv run python src/cli/dump_openapi.py && git diff --exit-code -- specs` | PASS | Local; OpenAPI regenerated and no spec diff |

### TypeScript and Web checks

| Command | Result | Evidence |
|---|---|---|
| `cd typescript && pnpm run format:check` | PASS | Local; all five workspace packages successful |
| `cd typescript && pnpm run lint` | PASS | Local; all five workspace packages successful |
| `cd typescript && pnpm run typecheck` | PASS | Local; all generated-client and app checks successful |
| `cd typescript && pnpm run build` | PASS | Local; site, admin web, and main web builds successful |
| `pnpm --dir apps/azents-web test` | PASS | Local; 121 tests passed |
| `pnpm --dir apps/azents-web build-storybook` | PASS | Local; Storybook production build completed |

### Testenv quality and E2E lanes

| Command | Result | Evidence |
|---|---|---|
| `cd testenv/azents/e2e && uv run ruff check .` | PASS | Local; all checks passed |
| `cd testenv/azents/e2e && uv run ruff format --check .` | PASS | Local; 64 files formatted |
| `cd testenv/azents/e2e && uv run pyright .` | PASS | Local; 0 errors/warnings/informations |
| Focused Ruff, format, and Pyright for `test_automatic_session_projects.py` after the CI correction | PASS | Local; all checks passed and 0 Pyright errors/warnings/informations |
| `uv run pytest --collect-only -q src/tests/azents/public/test_automatic_session_projects.py` | PASS | Static/collection; 5 feature E2E scenarios collected; all are marked `runtime_provider` |
| `uv run pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src` | UNAVAILABLE | Attempted; Docker network fixture failed before product tests because `/var/run/docker.sock` is absent |
| `uv run pytest -vv -m "runtime_provider and not live_external" ./src/tests/azents/public/test_automatic_session_projects.py` | UNAVAILABLE | Attempted; Docker-backed Runtime Provider fixture could not initialize |
| `uv run pytest -vv -m "web_surface and not live_external and not runtime_provider" ./src` | UNAVAILABLE | Attempted; Docker-backed gateway/browser fixture could not initialize |
| `git diff --check` | PASS | No whitespace errors in the phase diff |

The unavailable local lanes are an infrastructure limitation, not failed assertions. CI run `30103679601` supplied diagnostic execution for the focused Runtime Provider lane: the five feature tests reached Runtime startup but were blocked by the unsupported accepted-contract prerequisite. The first PR 6 Web Surface run exposed a test-fixture contract defect before the browser journey; the correction and subsequent diagnostic status are recorded below.

## Fixture readiness and test-boundary audit

The new E2E module `testenv/azents/e2e/src/tests/azents/public/test_automatic_session_projects.py` prepares state through supported product boundaries:

- creates Workspace, LLM integration, Agent, policy, and Sessions through generated Public API clients or HTTP API calls;
- creates disposable Runtime directories through `docker exec` against the test Runtime container, and removes one disposable directory through the same Runtime boundary for missing-path validation;
- uses fake Slack HTTP configuration, signed callback admission, generated External Channel API decisions, and public Session Project APIs;
- does not add a feature-specific browser journey; UI behavior is covered by existing `azents-web` unit/component tests, build, Storybook, and the repository's existing Web Surface regression lane;
- does not write product tables directly and does not contain live provider credentials.

A runtime-ready fixture is required for non-empty policy replacement; an explicit empty replacement does not require Runtime readiness. The unavailable-state scenario stops the deterministic Runtime Provider, performs the public API assertions, then waits for a new provider registration before restoring the fixture. This preserves fixture state for later tests.

## Requirement-to-validation matrix

| Requirement/scenario | Primary validation | Evidence/status |
|---|---|---|
| REQ-1: save multiple ordered default Projects | Public GET/PUT helpers and policy repository/service/API tests; UI behavior covered by existing Web tests/build/Storybook | Local backend/API tests and 121 Web tests PASS; PR6 selected deterministic/Web Surface lanes PASS in final CI |
| REQ-2: team-primary receives defaults | `_team_primary_session` followed by public Session Project API | Feature test executed in PR7 focused lane but blocked at `_prepare_runtime_workspace` / start-agent-runtime with HTTP 500 because no supported accepted-contract fixture prerequisite exists; not a product assertion failure |
| REQ-2: External Channel Allow creates root with defaults | Signed fake Slack admission → approval decision → Session Project API | Feature test executed in PR7 focused lane but blocked before the assertion at Runtime start with HTTP 500; no product assertion failure recorded |
| REQ-2: already-granted initial binding snapshots | Second resource/channel with same fake Slack principal after `allow_agent`; compare new Session snapshot | Feature test executed in PR7 focused lane but blocked before the assertion at Runtime start with HTTP 500; no product assertion failure recorded |
| REQ-3: explicit empty selection wins | Public `POST /chat/v1/agents/{agent_id}/sessions` with `existing_project_paths: []` | E2E assertion and backend tests present; local Docker unavailable; static/API path verified |
| REQ-3: explicit different selection is not merged | Public Session create with one alternate path; exact Session Project response assertion | E2E assertion and root-service tests present; local Docker unavailable |
| REQ-4: old/new snapshots | Existing automatic Session is retained; policy replacement; second automatic Session is compared | External Channel E2E asserts old Session remains on old paths and second Session uses new paths; local Docker unavailable |
| REQ-5: empty policy compatibility | Revision-1 empty policy and explicit clear paths; automatic creation remains available | Policy persistence/service/root tests present; focused local test evidence includes expected Docker skips |
| REQ-6: subagent shared context/no duplicates | Public subagent-tree and Session Project assertions | E2E scenario and root/subagent tests present; local Docker unavailable |
| REQ-7: existing-Project-only/no worktree provisioning | Root service creates context Project rows only; E2E seeds existing directories; no worktree controls in policy API | Static code/test inspection PASS; no new worktree/provider contract detected |
| Missing path save | Remove disposable Runtime directory, PUT complete policy, verify 400 and unchanged revision/policy | E2E scenario present; local Docker unavailable; backend service/API tests PASS from implementation phases |
| Runtime unavailable non-empty + clear | Stop Runtime Provider, verify non-empty 409 stable code, then empty clear 200 | Feature test executed in PR7 focused lane but blocked before the assertion at Runtime start with HTTP 500; no product assertion failure recorded |
| Concurrent revision conflict | Two expected-revision writes; stale write returns 409 and preserves winner | Repository/service/API tests and policy route tests PASS; E2E scenario support present |
| Web add/reorder/remove behavior | Existing `azents-web` unit/component tests, build, Storybook, and repository Web Surface regression lane | Web tests (121), build, Storybook, lint/typecheck PASS; final Web Surface selected checks PASS in CI; no new runtime-coupled browser journey |

## CI evidence

All timestamps and statuses below are from GitHub Actions on 2026-07-24.

| PR | Run | Branch relationship | Result |
|---|---:|---|---|
| #846 | `30091640958` | `feat/agent-default-projects-policy` → `feat/agent-default-projects-plan` | All required checks passed; deterministic and Web Surface E2E passed |
| #847 | `30091819918` | `feat/agent-default-projects-root-sessions` → `feat/agent-default-projects-policy` | All required checks passed; deterministic and Web Surface E2E passed |
| #848 | `30093103402` | `feat/agent-default-projects-external-channel` → `feat/agent-default-projects-root-sessions` | All required checks passed; deterministic and Web Surface E2E passed |
| #852 | `30098221747` | initial PR6 run | Deterministic E2E passed; Web Surface failed on the coupled feature browser scenario |
| #852 | `30100622354` | intermediate correction run | Deterministic E2E passed; Web Surface failed while diagnosing Runtime/provider readiness |
| #852 | `30101913288` | commit `9e956f82` | **All required PR6 checks passed**; deterministic lane selected 254 non-runtime-provider tests (243 passed, 11 skipped), Web Surface selected 6 existing tests and passed, and aggregate `ci-python-e2e` passed |
| PR7 diagnostic | `30103679601` | focused Runtime Provider diagnostic | Focused job `89515773976` collected 8 tests: the pre-existing 3 focused Runtime Provider tests passed; all 5 automatic-session Project tests executed but were blocked before assertions at Runtime startup. Deterministic and Web Surface lanes passed; aggregate E2E failed only because the focused job failed |

Runs `30098221747` and `30100622354` both passed deterministic E2E but failed Web Surface while the feature-specific browser scenario was coupled to Runtime/provider setup. The first run used the durable Provider resource ID where Agent creation requires the logical Provider ID; PR6 commit `f46c0148` corrected the fixture to use `system-docker`. The later run's diagnostics then showed `RuntimeProviderSelectionUnavailable` because the selected Provider capability contract had not yet been accepted, followed by Python 3.14 `FrozenInstanceError` while assigning `__traceback__` to a frozen exception. The latter pair are residual Runtime/provider readiness and frozen-exception observations outside this feature/PR scope.

PR7 diagnostic run `30103679601`, focused job `89515773976`, collected 8 tests. The three pre-existing focused Runtime Provider tests passed. All five automatic-session Project tests executed and failed at `_prepare_runtime_workspace` / `start-agent-runtime` with HTTP 500 before product assertions. Server logs reported `RuntimeProviderSelectionUnavailable` because no accepted capability contract was available, followed by Python 3.14 `FrozenInstanceError` while assigning `__traceback__` to the frozen exception. Deterministic and Web Surface lanes passed; aggregate `ci-python-e2e` failed only because the focused job failed.

The five feature tests are therefore **EXECUTED / BLOCKED BY MISSING SUPPORTED FIXTURE PREREQUISITE**, not product assertion failures and not pending terminal execution. Current Admin/Public APIs expose provider inventory, policy, and auth bindings, but no supported fixture path accepts the required provider capability contract. Direct product DB writes are prohibited by testenv policy. The validation phase does not expand into the separately scoped Runtime Provider contract lifecycle or frozen-exception fix.

## Failures and fixes

No approved-feature product implementation defect was identified. The coupled browser scenario first exposed an E2E fixture defect that confused the Provider resource ID with its logical ID; commit `f46c0148` corrected it. PR7 then executed the five feature tests but blocked all of them before product assertions because the repository has no supported accepted-contract fixture prerequisite. Server diagnostics also exposed the separately scoped Python 3.14 frozen-exception observation. The validation phase does not expand into Runtime Provider contract lifecycle management or the frozen-exception fix. The three local Docker-backed lane attempts remain blocked before fixture initialization by the missing Docker socket. Existing non-Docker quality, contract, focused backend, Web, and Storybook checks passed.

## Strict implementation versus current living specs

The implementation is aligned with the confirmed Requirements/ADR/Design, but the current living specs have not yet been promoted for this feature. The following are Phase 6 documentation inputs, not Phase 5 code defects:

### Aligned behavior already represented or compatible

- `workspace.md` and `conversation.md` describe Session Project APIs and the Agent Workspace boundary used by the new code.
- `external-channel.md` and the authorization/ingress flows retain the existing connection → binding → resource lock and transaction concepts that the External Channel integration preserves.
- Existing explicit Session Project behavior remains represented by the current Session Project routes.

### Implementation behavior missing from current specs

- `agent.md` does not document Agent-scoped automatic-session Project policy ownership, revisioned ordered paths, AgentAdmin-only GET/PUT management routes, stable policy error codes, or policy repository/service code paths.
- `workspace.md` does not document automatic-session policy persistence, Runtime-backed non-empty replacement validation, empty-clear behavior, coherent policy snapshots, or the distinction from recency-oriented `agent_project_defaults`.
- `conversation.md` does not document explicit versus Agent-default root workspace intent, team-primary winner-only policy application, policy revision provenance, automatic root creation without Runtime I/O, or subagent exclusion from policy application.
- `external-channel.md` does not state that a newly created binding Session snapshots the Agent policy into its root `SessionAgentContext`, while an existing binding reuses its immutable Session snapshot.
- `external-channel-authorization.md` does not describe policy snapshotting in the Allow/new-binding transaction or the already-granted initial-binding path.
- `external-channel-provider-ingress.md` does not describe the already-granted External Channel initial-binding root creation boundary.

### Stale or misleading current-spec language

- `conversation.md` currently models `AgentSession ||--o{ SessionWorkspaceProject` as the ownership relationship. The implementation's authoritative root Project membership is on the shared `SessionAgentContext`; direct context Project rows are inherited by subagent Sessions through the context. Phase 6 should correct the diagram and prose without changing the public Session Project API.
- `workspace.md` presents `SessionWorkspaceProject` as an `AgentSession`-owned resource and groups the legacy recency `agent_project_defaults` alongside policy-related project concepts. Phase 6 should distinguish context-owned immutable snapshots, Agent-scoped recency convenience state, and the new automatic-session policy.
- The External Channel authorization flow says only that an External Channel AgentSession is created when no active binding exists; it omits the shared root creation boundary and policy snapshot, which can make the current behavior appear incomplete.

No current spec contradicts an API response shape or requires a behavior that the implementation removed; the principal drift is omission and stale ownership terminology.

## Blockers and residual risks

1. **Local Docker substrate blocker:** `/var/run/docker.sock` is absent, so deterministic, Runtime Provider, and Web Surface E2E could not execute locally. CI is the authoritative executable source for these lanes.
2. **Supported Runtime Provider fixture prerequisite:** PR7 diagnostic run `30103679601` executed all five feature tests, but each was blocked at Runtime startup by HTTP 500 `RuntimeProviderSelectionUnavailable` because no accepted capability contract fixture is exposed through supported Admin/Public APIs. The aggregate E2E failure is diagnostic evidence only; this phase will not add direct DB writes or expand Runtime Provider contract lifecycle scope.
3. **Spec promotion remains outstanding:** current living specs need the Phase 6 updates listed above. This is intentional phase sequencing, not an implementation blocker.
4. **No live-provider evidence:** live Slack was intentionally out of scope; fake Slack coverage is the required credential-free path.

## Phase 6 spec-promotion inputs

Update the five candidate specs listed in the Design/Living Spec Updates section, preserving current API names and adding:

- policy tables, ordered normalized path identity, revision and error semantics;
- AgentAdmin permission boundary and Runtime validation/empty-clear distinction;
- root intent ADT and automatic root snapshot timing;
- team-primary race winner-only application and no Runtime I/O;
- External Channel new-binding and already-granted initial-binding snapshot behavior;
- SessionAgentContext ownership and subagent inheritance/no duplicate registration;
- separation from `agent_project_defaults`, presets, and catalog projections;
- current code paths and `last_verified_at` updates.

## Conclusion

Available evidence supports the approved `agent-260724` product behavior and shows no approved-feature implementation defect. PRs #846, #847, #848, and #852 are green for their selected required CI lanes. PR7 diagnostic run `30103679601` executed the five feature Runtime Provider tests, but all five were blocked before assertions by the missing supported accepted-contract fixture prerequisite; this is not a product assertion failure or pending terminal execution. Deterministic and Web Surface lanes passed, while aggregate E2E failed only because the focused job failed. Local Docker remains unavailable. This validation phase will not expand into Runtime Provider contract lifecycle management or the Python 3.14 frozen-exception fix; final Phase 5 records the blocker without modifying specs, Requirements, ADR, Design, code, tests, clients, or direct product DB state.
