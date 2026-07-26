---
title: "Multi-Agent Slack App Routing Testenv Validation Report"
created: 2026-07-26
document_role: supporting
document_type: supporting-validation-report
snapshot_id: slackapp-260725
tags: [external-channel, slack, validation, e2e, testenv, migration, security]
---

# Multi-Agent Slack App Routing Testenv Validation Report

## Scope and Boundaries

- Origin: `8/10 — E2E/testenv validation`
- Branch/base: `validation/slack-multi-agent-app` → `feature/slack-multi-agent-app-web`
- Requirements: [slackapp-260725/REQ](../requirements/slackapp-260725-multi-agent-routing.md)
- ADR: [slackapp-260725/ADR](../adr/slackapp-260725-multi-agent-routing.md)
- Design: [slackapp-260725/DESIGN](slackapp-260725-multi-agent-routing.md)

This report records deterministic fixture support, executed validation, blocked local evidence, and
the strict implementation-versus-living-spec comparison for the Single App/Multi App routing stack.
It is supporting evidence, not a living spec or a replacement for CI. A collected test, static check,
or local Docker-readiness failure is not reported as successful product E2E execution.

## Environment and Readiness Contract

Validation ran on Python 3.14.6 in the PR 8 worktree. Deterministic product E2E requires a Docker
daemon for the testcontainers-backed PostgreSQL, Valkey, object storage, Slack fake, server, and
worker topology. Product setup remains API-only; no test writes product rows directly.

The required local preparation path is:

```console
cd testenv/azents
uv run testenv bootstrap local
uv run testenv prerequisite prepare --profile live --json
uv run testenv fixture doctor <fixture-id> --json
uv run testenv fixture up <fixture-id> --json
```

The current runtime has neither a `docker` executable nor `/var/run/docker.sock`. `bootstrap local`
therefore stopped at `devserver-down`, and focused product E2E stopped while constructing the shared
Docker network before any product server, worker, migration, or scenario step ran. This is recorded as
a local environment blocker. The required GitHub deterministic E2E supplied the executable
product-evidence lane for this branch and completed successfully.

## Fixture Support Added

The deterministic Slack provider fake now supports the Multi App paths without retaining provider
secrets or visible participant content:

- configurable App, Team, and Bot User identities for distinct installations;
- `views.open` and `views.update` outcomes with deterministic view IDs and hashes;
- sanitized selector evidence containing callback ID, opaque private metadata, route IDs, and submit
  availability, but not trigger IDs or Agent display text;
- selector-control evidence containing action IDs and the opaque admission ID, but not message or
  button copy; and
- existing signed JSON Events API and form-encoded interactivity through the same fixed endpoint.

The E2E server fixture explicitly enables the rollout-gated Multi App surface. Production keeps the
gate disabled by default until every deployed API and worker instance is mode-aware.

## Executed Evidence

| Date (KST) | Command | Result | Evidence |
| --- | --- | --- | --- |
| 2026-07-26 | `cd python/apps/azents && uv run pytest src/azents/services/external_channel/interaction_test.py -q` | pass | `11 passed`; selector admission, modal, navigation, submission, metadata, and expiry tests passed. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest src/tests/test_slack_provider_fake.py -q` | pass | `16 passed`; distinct installation identity, redacted selector view/control evidence, and prefixed native Plan capture passed. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run ruff check . && uv run ruff format --check . && uv run pyright .` | pass | Ruff and formatting passed; Pyright reported `0 errors, 0 warnings`. |
| 2026-07-26 | `cd testenv/azents/e2e && uv run pytest ./src/tests/azents/public/test_external_channels.py --collect-only -q` | pass | All eight External Channel journeys collected, including the two new Multi App journeys. |
| 2026-07-26 | `cd python/apps/azents && uv run ruff check --fix . && uv run ruff format . && uv run pyright && uv run pytest` | pass | Ruff and formatting passed; Pyright reported `0 errors, 0 warnings`; Pytest reported `2531 passed, 611 skipped`. Docker-backed repository and migration cases were skipped by their existing environment guards. |
| 2026-07-26 | `cd python/apps/azents && uv run alembic -c db-schemas/rdb/alembic.ini heads` | pass | Reported the single expected head `cc31dfa97a1b`. |
| 2026-07-26 | `cd python/apps/azents && uv run pytest src/azents/rdb/external_channel_app_mode_migration_test.py --collect-only -q` | pass | All 13 app-mode migration cases collected, including legacy preservation, ambiguity rejection, and unsafe downgrade rejection. |
| 2026-07-26 | `cd testenv/azents && uv run testenv bootstrap local` | blocked | Exit code `1`; `.env` creation succeeded, then `devserver-down` failed because the runtime has no Docker executable or daemon. |
| 2026-07-26 | focused Multi App management and selector E2E node IDs | blocked | Both tests collected, then errored in the session `container_network` fixture because `/var/run/docker.sock` does not exist. No product scenario step ran. |
| 2026-07-26 | PR 7 TypeScript sequence: format, lint, typecheck, Web tests, build | pass | The parent Web branch reported format/lint/typecheck/build success and `123` passing Web tests before PR 8 branched from it. |
| 2026-07-26 | PR 6 GitHub `ci-python-run (python/apps/azents)` in run `30182642454` | pass | `3143 passed, 6 warnings`; all 13 App mode migration cases executed against Docker-backed PostgreSQL and passed. |
| 2026-07-26 | PR 8 GitHub `ci-tool-search-runtime-provider-e2e-run` in run `30182655125` | pass | `3 passed, 2 warnings`; the runtime-provider journey observed the Agent identity prefix followed by the native Plan and completed canonical work. |
| 2026-07-26 | PR 8 GitHub `ci-deterministic-e2e-run` in run `30182655125` | pass | `254 passed, 6 skipped, 22 deselected, 2 warnings`; both new Multi App journeys and the Slack fake regression suite passed. |

## Grounded Fixes Found During Validation

| Finding | Evidence | Fix | Verification |
| --- | --- | --- | --- |
| Selector service tests encoded an admission expiry as one day after the fixed date `2026-07-25`, so they began failing when real UTC time passed that date. | Seven full-suite failures raised `Slack selector admission is unavailable` before the intended assertions. Production correctly rejected the expired admission. | Replaced the calendar-fragile valid and expired fixtures with timezone-aware `datetime.max` and `datetime.min` boundaries. Production fail-closed expiry logic is unchanged. | Focused selector tests: `11 passed`; latest Docker-backed GitHub backend run: `3143 passed, 6 warnings`. |
| The Slack fake could not represent several App identities or drive modal callbacks without exposing transient triggers or visible copy. | Multi App setup and selector E2E had no deterministic provider evidence boundary. | Added configurable provider identity, modal mutation handling, and bounded redacted selector evidence. | Slack fake tests: `16 passed`; E2E Ruff, format, and Pyright passed. |
| The runtime-provider journey still assumed a native Plan was the first Slack block, but Agent-associated output now prepends the required Agent identity section. | Two GitHub runtime-provider runs reached completed canonical work and tool execution, then timed out because the fake omitted prefixed Plan blocks from its evidence. | Detect a native Plan anywhere in an update, retain the full ordered block payload, and assert that the Agent identity section precedes the Plan with a matching fallback prefix. Production delivery behavior is unchanged. | Slack fake tests: `16 passed`; E2E Ruff, format, and Pyright passed; corrected GitHub runtime-provider E2E: `3 passed, 2 warnings`. |
| No product E2E joined Workspace management, route/default lifecycle, mention selection, duplicate callbacks, approval, and final binding projection. | Existing External Channel E2E covered dedicated connection, approval, work, files, Socket Mode, and Web surfaces only. | Added one Workspace management journey and one mention-selector journey using public/admin APIs and signed callbacks. | Both journeys passed in the GitHub deterministic E2E lane; the complete lane reported `254 passed, 6 skipped, 22 deselected`. |

## Primary Matrix Status

| Requirement | Deterministic coverage | Current status |
| --- | --- | --- |
| `REQ-3`, `REQ-12` — legacy dedicated connection becomes Single without behavioral loss | Existing signed HTTP admission, connection lifecycle, Socket Mode, file, and work journeys; 13 migration cases cover legacy classification and downgrade safety. | Backend regression, all 13 Docker-backed migration cases, and deterministic product E2E passed. |
| `REQ-1`, `REQ-4` — Workspace authority and zero/populated Multi Apps | New management journey uses Owner, Manager, and Member identities; verifies Member denial, zero-Agent creation, route growth, redaction, and historical disconnect. | Deterministic management journey passed. |
| `REQ-2` — many-to-many App/Agent catalog without duplicate association | Management journey adds two Agents, repeats one association idempotently, creates a second Multi App, and associates the same Agent with both Apps. | Deterministic management journey passed. |
| `REQ-5`, `REQ-6` — selector catalog, source retention, and single selection | Interaction/selector/shortcut-source service tests cover signed scope, paging/search, stale scope, catalog access, and retained source continuation. New E2E drives a real modal and approval continuation. | Service and deterministic product E2E passed. File-bearing selector continuation remains covered below the product-E2E layer by source/file service tests. |
| `REQ-7` — channel default management and handoff authority | Management E2E sets, conflicts, invalidates, lists, and clears/default-related state through generation-fenced Workspace APIs; PR 7 Web tests cover management state. | Deterministic management journey passed; authenticated Slack-to-Web handoff remains covered by focused API/Web tests rather than a new browser E2E in this phase. |
| `REQ-8` — mention without default selects but does not create a default | New signed Events API mention, duplicate block action, modal, and submission journey starts with an empty default list and reaches one selected binding. | Deterministic mention-selector journey passed. |
| `REQ-9` — competing resolution creates one binding and Session | Repository/service lock-order, idempotency, stale-generation, and duplicate-callback tests run in the backend suite; the new E2E repeats event, block action, submission, and decision. | Backend and end-to-end duplicate paths passed. |
| `REQ-10` — access-required selection waits for Allow and releases source once | New E2E asserts pending approval has no Session, preserves source text, repeats the decision safely, then observes one active selected binding. | Deterministic mention-selector journey passed. |
| `REQ-11` — Multi association removal preserves App/other routes; Single removal disconnects | New management E2E verifies impact preview, route removal, surviving route, invalidated default, and terminal Multi disconnect; existing dedicated lifecycle tests cover Single disconnect. | Backend and deterministic management journey passed. |
| `REQ-13` — cross-scope and stale payloads fail closed | Management, selector, interaction, admission, and repository tests cover cross-Workspace IDs, cross-resource admissions, metadata tampering, removed routes, and stale generations. | Backend passed; the deterministic management journey passed its cross-Workspace not-found assertion. |
| `REQ-14` — Agent identity presentation and safe icon fallback | Presentation and delivery unit tests cover required leading Agent name and capability-aware icon projection across provider output types. | Backend and runtime-provider E2E passed, including the prefixed native Plan assertion. |
| `ADR-D7` — rollout gate | Configuration and management tests keep Multi creation disabled by default; the E2E server alone opts in explicitly. | Backend passed; the explicitly enabled deterministic E2E fixture passed. |

## Migration and Generated Contract Evidence

- The branch changes no migration or generated client artifact.
- Alembic exposes one head, `cc31dfa97a1b`.
- The 13 migration integration cases require Docker-backed PostgreSQL. All 13 executed and passed in
  the PR 6 GitHub Python CI lane.
- PR 6 generated Python and TypeScript clients from the Public OpenAPI. PR 8 imports those generated
  Multi App, route, default, invitation, role, and generation-fence types without editing generated
  output by hand.

## Pre-Promotion Living-Spec Comparison

The current living specs describe the pre-feature dedicated-App model. The implementation is
intentionally ahead of them until PR 9. No living spec is changed in this validation PR.

| Living spec | Implemented behavior not yet represented | PR 9 promotion action |
| --- | --- | --- |
| `spec/domain/external-channel.md` | Immutable `single`/`multi` App mode; Single cardinality of exactly one route; Multi cardinality of zero or more routes; route history snapshots; Workspace-owned Multi management; read-only disconnected Multi history. | Replace the dedicated-only route model and management surface with the verified mode-aware ownership and persistence invariants. |
| `spec/flow/external-channel-provider-ingress.md` | Mode-aware unbound resolution order; durable conversation admission; signed shortcut/block/modal callbacks; selector paging/search; no arbitrary candidate fallback. | Add interaction admission, selection, and binding resolution while preserving fixed-endpoint HMAC/Socket semantics. |
| `spec/flow/external-channel-authorization.md` | Selection before Agent-specific access evaluation; source provenance retained through approval; callback actor never becomes execution User; duplicate selection/decision convergence. | Add selector-to-approval continuation and the exact principal/owner-generation fences. |
| `spec/flow/external-channel-lifecycle.md` | Multi route removal, catalog re-enable, channel-default invalidation, generation-fenced impact operations, and disconnected Multi read-only retention; Single association removal disconnects the App. | Add mode-specific route, default, disconnect, and decommission semantics. |
| `spec/flow/external-channel-delivery.md` | Every Agent-associated Slack output starts with the bold Agent name; validated icon override is optional and provider-safe; selector and management controls are distinct from ordinary Agent output. | Add the verified presentation contract and fallback behavior without weakening durable delivery rules. |
| Agent/Workspace domain specs | Workspace Owner and Manager can read/write Multi management; ordinary Members cannot; Agent administrators retain Single authority only. | Promote permission ownership and the separate Agent/Workspace UI surfaces where the domain specs need it. |

## Completion Gate

The PR 8 validation gate is satisfied on head `361948f1`: GitHub run `30182655125` completed
successfully, including the deterministic, runtime-provider, and Web-surface E2E lanes. The parent
PR 6 Python lane also executed all Docker-backed migration cases successfully. The local Docker
blocker remains documented as an environment limitation and was not treated as successful evidence.
