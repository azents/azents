---
title: "Provider Channel Participation Phase 6 — Integrated Validation"
created: 2026-08-01
updated: 2026-08-02
tags: [external-channel, conversation, validation, e2e, testenv, frontend]
---

# Provider Channel Participation Phase 6 — Integrated Validation

## Phase Execution Plan

- Phase: `6 — Integrated Validation`
- Branch/base: `feature/conversation-channel-participation-validation` → `feature/conversation-channel-participation-lifecycle`
- PR boundary: Enable the approved participation contract in the credential-free E2E environment; replace pre-participation test expectations with deterministic Slack and Discord setup, location, settings, lifecycle, and management journeys; record strict implementation/spec and removal-absence evidence; and fix defects discovered by the integrated matrix without changing product intent.
- Inputs: Approved `conversation-260801` Requirements, ADR, Design, and multi-phase implementation plan; PRs 3–7 implementation; the Phase 5 checkpoint and independent review; current External Channel Living Specs; generated public clients; deterministic Slack and Discord provider fakes.
- Deliverables: A participation-enabled E2E server fixture; bounded provider-fake evidence and barriers required by the Design matrix; public API, signed callback, provider-control, and rendered-Web validation with no direct product-DB writes; corrected stale Web continuation fixture; exact command/environment/results record; strict implementation/spec comparison; Design removal-obligation audit and absence evidence.
- Non-goals: New product behavior, Living Spec edits or snapshot `implemented` markers, implementation-plan cleanup, live provider credentials, production rollout, rollout-gate removal, Kubernetes mutation, merge of any stacked PR, or compatibility fallback for pre-participation E2E behavior.
- Interfaces: Product state is created only through public APIs, rendered UI, signed Slack/Discord callbacks, and provider fakes. Provider-fake evidence remains categorical, bounded, and content-free. Bounded database reads are allowed only when public surfaces cannot prove an absence/count/lifecycle fact; direct product database writes are prohibited. Canonical mailbox admission, wake, and AgentRun remain independent of provider delivery results. Generated clients remain schema-generated.
- Removal obligations: Validate every Design removal row: no eager unconfigured target Binding/Session/mailbox path; no default thread Resource fallback; parent Slack delivery omits `thread_ts`; parent Discord delivery avoids thread provisioning; provider selection uses principal provenance without a synthetic User; Web setting mutations use User provenance; setup-linked Allow and selector paths do not enter legacy Binding replay; Slack/Discord settings dispatch is typed; required provider commands and settings controls replace selector-only/one-command/presence-only assumptions; selected-Agent replacement and clear terminalize parent participation while preserving threads/history; one selected parent Agent prevents fan-out; versioned existing-Binding controls do not rewrite history or blindly retry.
- Absence verification: Pair repository searches and exhaustive enum/union handling with deterministic E2E evidence. The matrix must prove no Session-owned execution state before location selection, no provider thread target for parent delivery, no synthetic actor fallback, no `replay_access_allow` for setup-linked authorization, no selector-to-Binding replay before location selection, no duplicate or revived terminal participation state, no parent fan-out, no legacy control idempotency reuse, and no secret/content/provider-identifier leakage in fake evidence or captured logs.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Deterministic provider and E2E implementation | `/root/pr8-validation-implementation-20260801` | `testenv/azents/e2e/src/support/{slack_provider_fake,discord_provider_fake}.py`, provider-fake tests, `testenv/azents/e2e/src/tests/conftest.py`, External Channel deterministic E2E tests | Stable PR 7 public/provider contracts and generated Python client | Participation-enabled fixtures; bounded setup/settings/command/location evidence; converted and new Slack/Discord journeys covering the primary matrix | Testenv Ruff/format/Pyright, fake contract tests, focused External Channel E2E, deterministic credential-free lane |
| Web regression normalization | `/root` | `typescript/apps/azents-web/src/features/chat/continuationPresentation.test.mts` and only directly affected Web tests | Canonical `external_channel_continuation` role contract | Stale metadata-based fixture replaced by the canonical role fixture without changing production behavior | Web unit suite, format, lint, typecheck, build |
| Removal and strict spec comparison | `/root` | Phase 6 plan/checkpoint and read-only searches across implementation, generated contracts, Helm, and current specs | Stable integrated diff and E2E results | Requirements/Design implementation matrix, current-spec drift table for PR 9, removal-absence table, sanitized environment/command evidence | Repository searches, OpenAPI/client drift, docs validation, diff/scope audit |
| Integration and final validation | `/root` | Integrated branch and phase checkpoint | Completed provider E2E and Web workstreams | Stable PR 8 diff, accepted fixes, independent review, complete validation record | Backend/testenv/TypeScript/Helm/full feasible suites according to affected boundaries |

- Integration order: Store and report this plan; hand the current contract and discovery map to the deterministic-validation owner; enable the E2E participation gate; extend bounded fake evidence before rewriting journeys; convert existing immediate-Binding expectations and add missing setup/location/settings/lifecycle journeys; fix the stale Web fixture; run focused lanes and correct defects; run removal/spec comparisons; request independent review; apply required fixes and targeted re-review; run final stable validation; update the checkpoint; commit and open PR 8.
- Independent review: `/root/pr7-lifecycle-independent-review-20260801` performs one read-only review of the stable PR 8 diff against Requirements, ADR, Design, the multi-phase plan, this phase plan, testenv rules, and recorded evidence. Review prioritizes E2E semantic validity, no-direct-DB-write compliance, provider-fake fidelity and redaction, absence proofs, stale/duplicate/failure paths, lifecycle preservation/no-revival, and whether fixes preserve product intent. Targeted re-review follows the code-review criteria.
- Final validation: Testenv Ruff format/check and full Pyright; Slack/Discord fake contract tests; focused External Channel deterministic E2E; full credential-free deterministic lane; applicable Web Surface E2E; backend Ruff/Pyright/focused or full Pytest when production code changes; public OpenAPI dump plus Python/TypeScript generated-client drift checks; Python client tests; TypeScript format/lint/typecheck/unit/build/Storybook; Helm render tests when rollout fixtures change; docs validation through commit hooks; removal searches; `git diff --check`.
- Scope-drift check: Compare the branch against PR 7 and this plan. Remove Living Spec edits, implemented markers, plan deletion, live-provider requirements, product redesign, rollout-gate removal, direct DB mutations, legacy compatibility branches, unrelated E2E cleanup, or infrastructure changes.
- Context checkpoint: Record the exact environment and tool versions, fake prerequisite state, scenario-by-scenario E2E results, fixes and invalidated evidence rerun, generated-contract drift result, Web result, implementation/spec differences reserved for PR 9, removal-absence evidence, independent review result, remaining PR 9/10 scope, risks, and blockers before commit and PR creation.

## Initial Discovery Checkpoint

- The E2E server fixture currently enables Multi App behavior but not `AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED`; PR 8 must enable it only in deterministic E2E while production and Helm defaults remain disabled.
- Existing Multi selector and Discord Gateway journeys encode pre-participation selector-to-immediate-thread-Binding behavior. They must be replaced by setup-claim and location-selection assertions rather than preserved behind a compatibility path.
- The public API exposes management/default/impact/Session projections but no participation-setting CRUD endpoint. Provider setup and settings mutations therefore enter through signed Slack/Discord callbacks; public APIs create connections, routes, Agents, and read projections.
- Slack fake delivery evidence already captures provider delivery outcomes and `thread_ts`, but needs bounded setup/settings control, scope, generation, Slash/context/modal, and installation-contract evidence.
- Discord fake already supports signed interactions, Gateway dispatch, delivery scenarios, and a delivery barrier, but needs deterministic command list/create/update/delete role state plus setup/settings scope evidence.
- `continuationPresentation.test.mts` is stale: it supplies `goal_continuation` with legacy metadata while the product and current specs use the canonical `external_channel_continuation` role.
- Current specs are comparison inputs only in this phase. Any documented drift is carried to PR 9 rather than edited here.

## Integrated Validation Checkpoint

### Environment

- Validation date: `2026-08-02`
- Base commit: `977997d33` (`feature/conversation-channel-participation-lifecycle`)
- Python: `3.14.6`
- uv: `0.11.1`
- Docker: `28.5.2`
- Node.js: `24.18.1`
- pnpm: `11.15.1`
- The deterministic E2E server fixture sets
  `AZ_EXTERNAL_CHANNEL_PARTICIPATION_ENABLED=true`. Backend configuration and
  Helm values remain disabled by default.
- Docker remained operational for the final feature lane. `docker info`
  continued to report CDI watcher `too many open files` warnings, but the final
  sequential and integrated runs completed successfully.

### Defects Found and Corrected

| Finding | Correction | Regression evidence |
| --- | --- | --- |
| Slack modal submission compared the new submission interaction ID with metadata signed by the authenticated settings-open interaction, rejecting valid later submissions. | Revalidate the processing submission interaction and separately lock and validate its authenticated origin interaction, connection, principal, and terminal processing status. | `interaction_test.py`; Slack approval, setup, and settings E2E journeys |
| A parent-channel Discord Message Command materialized only the legacy selector source, so route selection could replay toward a Binding before location selection. | Materialize or refresh a setup claim from the content-free shortcut source and link a setup selector to the claim. Route selection now advances setup without creating a Binding. | `shortcut_source_test.py`; Discord Message Command and Multi lifecycle E2E |
| The Web Surface test had drifted from the unchanged valid Slack setup contract by expecting `reconnect_required` from a successful fake `auth.test`. | Restore the existing `active` status and validated Team identity assertions. | Focused rendered-Web E2E |

### Commands and Results

| Boundary | Command summary | Result |
| --- | --- | --- |
| Backend static and focused tests | Ruff format/check for the four affected modules, whole-app Pyright, and `interaction_test.py`, `shortcut_source_test.py`, `selector_test.py` | `26 passed`; Ruff and Pyright clean |
| Testenv static and fake contracts | Ruff format/check for `src`, whole-testenv Pyright, Slack and Discord fake contract tests | `49 passed`; Ruff and Pyright clean |
| External Channel deterministic E2E | `pytest -vv -m "not web_surface" test_external_channels.py` | `12 passed, 1 deselected` |
| Rendered Web Surface E2E | Focused `test_connection_management_web_surface_uses_redacted_operational_state` | `1 passed` |
| Repository-wide deterministic E2E | `pytest -vv -m "not live_external and not runtime_provider and not web_surface" ./src` | `303 passed, 6 skipped, 23 deselected` |
| Web unit and build validation | `pnpm --filter @azents/web test`; Turbo format check, lint, typecheck, and build for `@azents/web` | `140 passed`; all four build checks successful |
| OpenAPI drift | Dump public and admin OpenAPI documents and compare tracked specifications | No tracked schema change |
| Generated TypeScript client drift | The Web build dependency regenerated `@azents/public-client` from the dumped public schema | No tracked generated-client change |
| Repository hygiene | `git diff --check` and scope comparison against PR 7 | Clean |

An earlier local External Channel all-at-once attempt lost the Docker daemon
after the first successful scenarios. After the daemon recovered, the stable
diff passed every External Channel scenario sequentially, the complete 12-test
non-Web feature file in one process, its separate rendered-Web test, and the
repository-wide credential-free deterministic lane. The focused Slack Multi,
Discord Gateway, and Discord Message Command scenarios were rerun after the
independent-review assertion corrections and all three passed.

### Current Living Spec Comparison

PR 8 records these differences without editing the Living Specs. PR 9 owns the
promotion and `last_verified_at` updates.

| Current spec statement | Integrated implementation | PR 9 action |
| --- | --- | --- |
| The External Channel domain defines provider conversations as Slack threads or Discord roots/threads and says a newly authorized conversation creates a Binding and real Session. | A provider parent channel is a first-class Resource. An unconfigured parent first creates or refreshes a setup claim and creates no Binding or Session before location selection. | Add parent Resource, participation setting, setup claim, location, and provenance invariants. |
| Provider ingress says original triggers immediately commit the Session, Binding, mailbox input, and wake after provider history. | Parent-channel admission first resolves participation. Canonical ingestion and wake begin only after a valid setting/location is selected; provider controls do not gate them. | Document the participation gate and setup replay boundary before canonical ingestion. |
| Authorization says Allow creates or reuses the Binding and replays synchronous ingestion. | Setup-linked Allow commits authorization and resumes the setup claim at location selection without entering `replay_access_allow` or creating a Binding. | Split setup-linked authorization from the retained legacy thread-Allow path. |
| Delivery says a Discord root Resource ensures a provider thread for all subsequent output. | Parent-channel Discord delivery remains in the parent channel. Thread provisioning remains authoritative only for thread Resources. | Add Resource-type-aware Slack and Discord delivery targeting. |
| Initial presence contains only `View session`. | New Bindings include settings access, and existing Bindings receive one versioned settings-available control without rewriting provider history. | Document provider-native settings controls and versioned reconciliation. |
| Provider interaction specs cover selectors and the single Discord Message Command but not the complete settings contract. | Slack supports Slash, channel/message settings, and signed modal setup/settings paths. Discord reconciles three required command roles and typed setup/settings components while preserving unrelated commands. | Document complete Slack manifest/dispatch and Discord command reconciliation contracts. |
| Multi default replacement and clear do not describe parent participation state. | Replacement and clear terminalize the prior parent setting, setup claim, and parent Binding while preserving established thread Bindings and history. | Add atomic parent participation terminalization and one-selected-Agent behavior. |
| Conversation continuation already uses the dedicated `external_channel_continuation` role. | Web presentation now tests the canonical role rather than inferring External Channel behavior from legacy metadata. | Preserve the current conversation spec; refresh verification only if its code-path audit requires it. |

### Removal and Absence Audit

| Design removal obligation | Integrated absence evidence |
| --- | --- |
| Eager top-level Binding, Session, and mailbox creation | Slack HTTP, Slack Multi, Socket Mode, Discord Gateway, and Discord Message Command journeys compare Session projections before location selection and find no Binding or Session-owned execution state. |
| Default thread Resource resolution | Production resolution exhaustively distinguishes parent and thread scopes; parent setup E2E creates the parent Resource only after location selection. Repository search finds no `_resolve_resource` default helper. |
| Slack parent replies carrying `thread_ts` | Resource-type-aware delivery rejects a parent scope with `thread_ts`; provider-fake evidence distinguishes absent parent targeting from retained thread targeting. |
| Discord root always provisioning a delivery thread | Parent setup and settings E2E assert no `create_thread` or provider message before location selection; parent delivery uses the channel while thread Resources retain `ensure_thread`. |
| Synthetic User for provider selection | Database constraints require exactly one User-or-principal provenance. Provider journeys mutate through the authenticated principal path without creating a User mapping. |
| Principal-only participation-setting provenance | The setting model requires exactly one User-or-principal configurator; Web and provider services clear the alternate actor field on mutation. |
| Setup-linked Allow entering Binding replay | `access_test.py` asserts `replay_access_allow` is not awaited, and the signed approval E2E remains without a Binding until location selection. |
| Setup selector replaying toward a Binding | Setup-linked selectors carry `setup_claim_id`; route selection advances the claim to location selection and E2E proves no pre-location Binding. |
| Incomplete Slack installation contract | Fake contract and provider E2E assert commands scope, Slash command, both message shortcuts, interactivity, and typed setup/settings controls. |
| Selector-only Slack dispatch | Parser and interaction tests cover command, action, context, and modal paths. Settings submissions validate their authenticated origin rather than falling through selector handling. |
| One stored Discord Message Command | Fake and activation E2E assert three required roles, distinct transient IDs, obsolete Azents command cleanup, and unrelated command preservation. |
| Presence with only `View session` | Delivery tests and E2E evidence cover settings access on new Bindings and one versioned settings-available control for existing Bindings. |
| Provider participant using AgentAdmin mutation | Provider settings paths use signed principal admission; Web management retains User authorization. No synthetic-admin fallback is present. |
| Default replacement leaving stale parent state | Slack and Discord Multi lifecycle journeys assert replacement/clear impact and terminalization while established thread history remains. |
| Multiple parent Agents or fan-out | Unique parent-setting constraints and E2E route selection prove one active selected route, setting, and parent Binding. |
| Legacy control idempotency gaining new payload | Settings-available delivery uses a distinct versioned origin. Repository tests cover delivered, failed, unknown, missing, and disconnected legacy states without retrying or rewriting history. |

### Provider-Fake Evidence Audit

- Slack `/__testenv/state` exposes only bounded request counts, sanitized request
  metadata, categorical deliveries, categorical view evidence, and Socket counts.
  Signed private metadata and route IDs remain in the separate transient-view
  handoff.
- Discord `/__testenv/state` exposes categorical command roles, interaction
  outcomes, operations, deliveries, and bounded Gateway evidence. Signed custom
  IDs and command IDs are available only through consume-once or transient test
  endpoints and are absent from persistent evidence.
- Fake contract tests assert that credentials, signatures, message bodies,
  filenames, file contents, transient custom IDs, and command IDs are absent
  from rendered evidence.
- The changed E2E diff contains no direct product database mutation. State is
  created through public APIs, signed provider callbacks, provider fakes, and
  rendered Web interactions.

### Independent Review

The assigned reviewer `/root/pr7-lifecycle-independent-review-20260801`
performed a read-only review of the stable diff and reported no production
Critical or Warning findings. Three E2E-proof Warnings were corrected:

1. Discord provider-control evidence now asserts exact ordered Session-path
   cardinality instead of using a duplicate-tolerant set comparison.
2. Slack Multi selector setup now proves that the original invocation becomes
   exactly one canonical non-pending mailbox/history item with its source body,
   authorization, message identity, and permalink preserved.
3. Discord Gateway and Message Command setup now compare exact pre-location
   Session ID baselines, so a newly created empty Session cannot evade the
   no-Session absence assertion.

The same reviewer completed a targeted read-only re-review and confirmed all
three Warnings resolved with no remaining Critical or Warning findings.

### Scope Checkpoint

- No Living Spec, Requirements, ADR, Design, migration, generated client, or
  production/Helm rollout-default change is included.
- Production fixes are limited to the two defects exposed by the deterministic
  setup and settings journeys and include focused regression tests.
- The remaining phases are PR 9 for Living Spec promotion and implemented
  snapshot markers, followed by PR 10 for implementation-plan cleanup.
- Independent review result: no remaining Critical or Warning findings.
