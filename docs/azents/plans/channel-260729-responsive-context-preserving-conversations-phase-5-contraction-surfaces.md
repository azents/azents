---
title: "Responsive Context-Preserving External Conversations Phase 5 Contraction and Surfaces Plan"
created: 2026-07-29
updated: 2026-07-29
tags: [external-channel, contraction, api, frontend, migration]
---

# Phase Execution Plan

- Phase: `5 — Contraction and Surfaces`
- Branch/base:
  `feature/channel-responsive-context-07-contraction-surfaces` →
  `feature/channel-responsive-context-06-cutover-qualification`
- PR boundary: Remove the qualified legacy event, hydration, activation, and pending-context
  authority; extract provider-control delivery and bounded recovery from the retired Event
  Processor; contract the public Session Channels projection and generated clients; and
  remove the corresponding obsolete UI while preserving the canonical synchronous
  conversation, delivery, file, interaction, access, and Session behavior.
- Inputs:
  - approved `channel-260729` Requirements, ADR, and Design from PR #1023;
  - multi-phase implementation plan from PR #1024;
  - additive position, range, wake, and preflight foundation from PR #1026;
  - provider-neutral synchronous ingestion from PR #1027;
  - Slack HTTP, Slack Socket Mode, and Discord Gateway transport cutover from PR #1028;
  - deterministic cutover qualification and the strict pending-control diagnostic from
    PR #1029;
  - closed PR #1020 as the exact historical finished-Discord-activation cleanup source.
- Deliverables:
  - one generated Alembic contraction revision with upgrade guards that reject any
    remaining legacy backlog or ownership and a downgrade that restores the retired
    schema shape without inventing discarded runtime data;
  - removal of `external_channel_events`, `external_channel_pending_contexts`, legacy
    hydration, activation, truncation, projection-position, and revision source-event
    schema, models, enums, repository DTOs/operations, lifecycle counts, and dead tests;
  - removal of the one-time finished Discord activation recovery query, reconciliation
    branch, stale-mailbox cleanup path, and historical fixtures from closed PR #1020;
  - a dedicated provider-control delivery service that preserves committed-intent
    authority, connection/credential revalidation, sole-attempt fencing, provider I/O
    outside database transactions, terminal settlement, and bounded recovery for pending
    or interrupted control attempts;
  - selector, approval, interaction, Slack HTTP/Socket, Discord HTTP/Gateway, and
    management callers using typed synchronous ingestion or the retained interaction
    lifecycle without depending on the Event Processor;
  - removal of the PR #1029 strict xfail after the recovered pending Slack progress-create
    intent is delivered through the new provider-control owner;
  - removal of `activation_status`, `truncated_message_count`, and `truncated_size` from
    `ManagedBinding`, OpenAPI, generated Python and TypeScript public clients, E2E
    consumers, Session Channels stories, and UI;
  - removal of only the obsolete activation and retained-context locale keys from every
    azents-web locale;
  - temporary cutover-gate source removal in this PR while retaining the documented
    operational rule that this PR is merge- and deployment-ineligible until the external
    checkpoint is explicitly completed.
- Non-goals:
  - no current living-spec promotion or `implemented` date;
  - no compatibility fallback, dual read, legacy processor restoration, or in-memory
    provider-control fallback;
  - no manual edits to generated clients;
  - no final post-contraction E2E evidence report assigned to PR 8;
  - no live database migration, ingress quiesce, deployment, Kubernetes mutation,
    provider mutation, production preflight, manual repair, PR merge, or operational
    checkpoint claim.
- Interfaces:
  - `ExternalChannelConversationIngestionService` remains the only normal provider-message
    application boundary. Normal message transport adapters do not persist raw callbacks
    or recreate a deferred event inbox.
  - Provider-control delivery is a separate application service over durable delivery
    attempts. Its claim transaction commits before provider I/O; provider I/O runs
    without an open transaction; final settlement re-locks and revalidates the same
    attempt and authority.
  - Recovery scans only bounded eligible control attempts in `pending` or stale
    `attempting` state, uses the existing delivery-attempt fencing and safe failure
    classification, and never retries an ambiguous provider write as though it were
    definitely absent.
  - Interaction and revocation lifecycle callbacks remain processable. Ordinary provider
    messages stay on typed synchronous ingestion.
  - PostgreSQL conversation positions and invocation wake state remain the ordering and
    execution authority. Redis and memory locks remain coordination only and are not
    changed by contraction.
  - Canonical provider-history revisions remain readable. New revisions have no
    `source_event_id`; downgrade restores nullable legacy columns/tables but does not
    reconstruct deleted legacy event or pending-context rows.
  - Public APIs expose no cursor, lock, boundary, omission, hydration, activation, or
    truncation state.
  - Generated clients are produced only from the regenerated public OpenAPI document.
  - Session Channels retains connection state, activity, Channel Work, delivery history,
    grants, disconnect behavior, archive behavior, and responsive layout.

| Workstream | Owner | Owned paths | Depends on | Output | Validation |
| --- | --- | --- | --- | --- | --- |
| Phase plan and contraction migration | `/root` | This plan; `python/apps/azents/db-schemas/rdb/`; `python/apps/azents/src/azents/rdb/models/external_channel.py`; migration/schema tests | PR #1029 qualification and current revision `acd4e70d9c19` | Generated guarded contraction revision, revision pointer, model contraction, upgrade/downgrade coverage | Alembic generation/revision checks; migration tests; schema metadata tests |
| Legacy persistence and processor removal | `/root` | `python/apps/azents/src/azents/core/enums.py`; `repos/external_channel/{data.py,repository.py,lifecycle.py,management.py,management_data.py,work.py}` and focused tests; `services/external_channel/{admission.py,event_processor.py,shortcut_source.py,access.py}` and focused callers/tests | Contraction schema contract and typed ingestion boundaries | No event/pending-context/hydration/activation runtime model or repository ownership; PR #1020 cleanup incorporated | Focused repository/service tests; full external-channel backend tests; static search proving retired symbols absent |
| Provider-control extraction and recovery | `/root` | New focused service/tests under `services/external_channel/`; `interaction.py`, `discord_selector.py`, `discord_http.py`, `http_admission.py`, public routes/composition, delivery repositories/tests | Existing durable delivery-attempt model and provider adapters | Dedicated one-attempt delivery, bounded pending/stale recovery, provider settlement, and no Event Processor dependency | Race/recovery/failure tests; route post-commit delivery tests; runtime-provider progress journey passes without xfail |
| Public API and generated clients | `/root` | `repos/external_channel/management_data.py`; public management route/tests; `python/apps/azents/specs/public/openapi.json`; generated Python and TypeScript public clients through generation commands | Backend projection contraction | Retired ManagedBinding fields absent from API and both clients | OpenAPI dump/check; generated-client commands; contract tests; client build/type checks |
| Session Channels UI and E2E consumers | `/root` | `typescript/apps/azents-web/src/features/session-channels/`; all four locale files; focused stories/tests; `testenv/azents/e2e/src/tests/azents/public/test_external_channels.py` | Generated TypeScript client | Activation badge and retained-context summary removed while remaining channel information and controls are preserved | TypeScript format/lint/typecheck/build; Storybook/component checks; focused E2E |
| Independent review | `/root/channel-responsive-reviewer` | Read-only complete Phase 5 diff | Stable integrated diff and validation evidence | Data-loss, migration, recovery, provider-I/O, API, generated-artifact, UI, and scope findings | One review report; targeted re-review only for qualifying findings |

- Integration order:
  1. Primary freezes the contraction inventory, generates the new Alembic revision, and
     writes failing migration/model contract tests before deleting runtime symbols.
  2. Primary extracts provider-control delivery and recovery from the Event Processor,
     migrates all retained selector/approval/interaction callers, and makes the PR #1029
     runtime-provider journey pass without the expected-failure marker.
  3. Primary replaces any remaining transient `ExternalChannelEventCreate` dependency
     needed by synchronous transports with a typed trigger/boundary DTO that carries no
     durable legacy processing state.
  4. Primary removes legacy event, hydration, activation, pending-context, and PR #1020
     persistence/service paths, then aligns lifecycle, management, work, composition, and
     tests with the canonical retained model.
  5. Primary contracts `ManagedBinding`, regenerates OpenAPI and both public clients, and
     updates backend and E2E contract consumers.
  6. Primary removes obsolete Session Channels UI, story fixture fields, and locale keys,
     preserving the existing layout and remaining information hierarchy.
  7. Primary removes the temporary cutover-gate implementation only after repository
     preflight tests prove the contraction guard. The plan and PR body retain the external
     merge/deployment checkpoint.
  8. Primary runs focused checks after each workstream, then full backend, generated
     client, TypeScript, and affected E2E validation on the stable integrated diff.
  9. Primary requests one read-only review from `/root/channel-responsive-reviewer`,
     batches grounded corrections, and requests targeted re-review only for
     requirements/design, security/data-loss, migration, or material interface findings.
  10. Primary records the Phase 5 checkpoint, commits, pushes, and opens PR 7 before
      beginning final validation work.
- Independent review:
  - Scope: complete Phase 5 diff against `channel-260729/REQ-10`, accepted ADR decisions,
    Design contraction/control-delivery/public-contract sections, PR #1029 qualification
    evidence, closed PR #1020 cleanup intent, and this phase boundary.
  - Criteria: migration aborts before destructive changes on any nonzero or ambiguous
    legacy state; downgrade is structurally valid and honest about discarded data;
    canonical messages/revisions/bindings/work/delivery/files/interactions/access/Session
    state remain authoritative; provider-control recovery cannot double-write or hide an
    ambiguous outcome; provider I/O is outside transactions; no legacy Event Processor
    owner remains; ManagedBinding and generated clients contract consistently; UI removes
    only obsolete information; no compatibility, live mutation, spec promotion, or PR 8
    work enters the diff.
  - Output: grounded Critical/Warning findings with exact paths, or explicit no findings.
- Final validation:
  - generated contraction migration upgrade/downgrade and repeated zero-backlog/ownership
    preflight tests;
  - focused external-channel repository, ingestion, replay, access, interaction,
    management, lifecycle, delivery, and control-recovery tests;
  - static search for retired tables, fields, enums, processor composition, PR #1020
    recovery symbols, and obsolete public/UI keys;
  - `cd python/apps/azents && uv run ruff format --check <changed Python paths>`
  - `cd python/apps/azents && uv run ruff check <changed Python paths>`
  - `cd python/apps/azents && uv run pyright`
  - `cd python/apps/azents && uv run pytest`
  - `cd python/apps/azents && uv run python src/cli/dump_openapi.py`
  - public Python and TypeScript client generation through the project generation commands
  - `cd typescript && pnpm run format`
  - `cd typescript && pnpm run lint`
  - `cd typescript && pnpm run typecheck`
  - `cd typescript && pnpm run build`
  - focused Session Channels Storybook/component tests
  - `cd testenv/azents/e2e && uv run ruff format --check src`
  - `cd testenv/azents/e2e && uv run ruff check src`
  - `cd testenv/azents/e2e && uv run pyright .`
  - focused runtime-provider progress journey with no xfail
  - affected deterministic External Channel E2E
  - `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check`
  - `python -m unittest scripts.tests.test_gen_docs_index`
  - `git diff --check`
- Scope-drift check:
  Compare the final diff with the deliverables and non-goals above. Remove current-spec
  promotion, implemented snapshot dates, final validation-report work, unrelated UI
  redesign, compatibility fallbacks, manual generated-client edits, infrastructure
  changes, live-provider credentials/evidence, deployment commands, and any claim that
  the external operational checkpoint has occurred.
- Context checkpoint:
  Record the migration revision and guard categories, deleted legacy schema and symbols,
  retained canonical authorities, provider-control claim/recovery/settlement behavior,
  PR #1020 cleanup disposition, ManagedBinding/OpenAPI/client/UI contraction, exact
  validation results, independent review disposition, operational merge/deployment
  blocker, and remaining PR 8/9/10 scope before opening PR 7.

## Phase 5 Checkpoint

Pending implementation.
