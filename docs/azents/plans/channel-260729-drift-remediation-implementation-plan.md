---
title: "channel-260729 Requirements Drift Remediation Implementation Plan"
created: 2026-07-30
updated: 2026-07-30
tags: [external-channel, slack, discord, reliability, security, validation]
---

# channel-260729 Requirements Drift Remediation Implementation Plan

## Feature summary

This plan closes the remaining implementation drift against the immutable
[`channel-260729/REQ`](../requirements/channel-260729-responsive-context-preserving-conversations.md),
[`channel-260729/ADR`](../adr/channel-260729-responsive-context-preserving-conversations.md),
and
[`channel-260729/DESIGN`](../design/channel-260729-responsive-context-preserving-conversations.md)
snapshot.

The synchronous provider-history ingestion foundation remains authoritative. This
remediation preserves its provider-neutral service, PostgreSQL conversation positions,
Redis or in-memory coordination, immutable invocation batches, mailbox admission, wake
recovery, and retired-inbox cutover. It corrects four implementation gaps:

1. Pending access and selector state currently persists provider content before
   authorization instead of retaining a metadata-only replay boundary.
2. Bot and system callbacks can consume a durable conversation position, and configured
   bots can become execution triggers, instead of remaining context for a later
   authorized human trigger.
3. Edit and delete lifecycle and revision classifications remain in the database,
   backend domain, mailbox and event contracts, API presentation, tests, and Web UI even
   though they are not current product behavior.
4. Discord provider-history projection drops visible embeds before canonical Session
   input construction.

The existing Requirements, ADR, and primary Design are implemented historical records
and are not modified by this work. Current specs and validation evidence are corrected
only after implementation validation.

## Delivery shape

The work uses a six-PR stack because it crosses admission security boundaries, database
and public API contracts, backend and Web presentation, provider normalization,
generated clients, deterministic E2E fixtures, and living specs.

Stack prefix: `channel-260729 drift remediation`

| Order | Branch | Base | PR boundary |
| --- | --- | --- | --- |
| 1 | `feature/channel-260729-drift-01-plan` | `main` | This multi-phase implementation plan |
| 2 | `feature/channel-260729-drift-02-admission` | PR 1 branch | Metadata-only pending boundaries and context-only author admission |
| 3 | `feature/channel-260729-drift-03-message-contract` | PR 2 branch | Edit/delete contract removal and Discord embed fidelity |
| 4 | `feature/channel-260729-drift-04-validation` | PR 3 branch | Full regression and deterministic E2E validation evidence |
| 5 | `feature/channel-260729-drift-05-specs` | PR 4 branch | Living-spec and validation-report correction |
| 6 | `feature/channel-260729-drift-06-cleanup` | PR 5 branch | Removal of this plan and all remediation phase plans |

Every implementation PR adds its own phase execution plan under `docs/azents/plans/`
before code changes begin. No later phase starts before the preceding phase PR exists.

## Sources of truth and fixed boundaries

### Requirements trace

| Requirement | Remediation obligation |
| --- | --- |
| `channel-260729/REQ-3` | A callback that is not a valid authorized trigger creates no input or wake and does not consume context needed by a later valid trigger. |
| `channel-260729/REQ-4` | Humans remain provider-history context regardless of Agent access; other bots and provider-visible system messages remain context-only; Discord embeds reach canonical Session input. |
| `channel-260729/REQ-6` | Position rechecks and atomic batch, mailbox, Session-running, and cursor behavior remain unchanged for accepted human triggers. |
| `channel-260729/REQ-7` | Pending access and selector state retains only typed identity and ordering boundaries; provider content becomes durable only during authorized acceptance. |
| `channel-260729/REQ-8` | Edit and delete callbacks are zero-artifact no-ops and no current product contract exposes edit or delete lifecycle classifications. |
| `channel-260729/REQ-10` | No raw-event inbox, pending-context fallback, or background event processor is restored. |

### ADR trace

| Decision | Preserved or corrected behavior |
| --- | --- |
| `channel-260729/ADR-D1` | All authenticated transports continue to use the shared synchronous ingestion service for valid human create triggers. |
| `channel-260729/ADR-D2` | Conversation locks remain ephemeral coordination; PostgreSQL position comparison remains the durable acceptance authority. |
| `channel-260729/ADR-D3` | Access and selector replay boundaries become genuinely metadata-only; Allow and route selection continue through the shared ingestion service. |

### Non-goals

- Do not restore `external_channel_events`,
  `external_channel_pending_contexts`, the Event Processor, hydration activation, or
  pending-context recovery.
- Do not modify the implemented Requirements, accepted ADR, or implemented primary
  Design.
- Do not change grant, block, or human open-access authorization decisions except where
  content is persisted relative to those decisions.
- Do not rewrite or remove previously accepted Session transcript events.
- Do not add a compatibility fallback for removed route, lifecycle, or revision
  contracts.
- Do not change provider delivery, Channel Work, Session broker, or unrelated Redis
  behavior.
- Do not perform a live database, Kubernetes, Argo CD, or deployment action as part of
  repository implementation.

## Ownership and review

| Role | Owner | Responsibility |
| --- | --- | --- |
| Primary implementation and integration | `/root` | Plan, branch stack, backend integration, migrations, generated artifacts, validation, and PR orchestration |
| Independent reviewer | `hardtack` via `/root/channel-responsive-reviewer` | Read-only review of each phase contract and diff; requirements, security, data-loss, API, and migration correctness |
| Backend workstreams | Assigned per phase | External-channel services, repositories, RDB models, mailbox and event contracts, API models |
| Web workstream | Assigned per phase when active | Approval and external-message presentation, generated client consumption, stories and translations |
| Testenv workstream | Assigned in validation phase | Provider fakes, deterministic E2E, sanitized evidence |

The primary owner gives every implementation owner the exact reviewer identity and
phase contract. Each implementation owner runs focused checks and directly requests the
independent review. Required findings are corrected in one batch, followed by targeted
re-review only for requirements/design, security/data-loss, or material
convention/interface corrections.

## Phase 1 — Metadata-only admission and context-only authors

### Deliverables

- Split canonical message identity persistence from authorized content and revision
  persistence.
- Pending access requests and pending selector admissions persist only:
  - connection and provider scope;
  - provider message identity and position;
  - initiating principal identity when available;
  - conversation-position row;
  - exclusive range start and inclusive trigger position; and
  - route or selection authority metadata.
- Pending state persists no normalized body, message revision, attachment metadata,
  reference mappings, attachment URL, or provider permalink.
- Human grant, block, open-access, and approval decisions are evaluated before provider
  content becomes durable.
- Allow and selector replay fetch provider history again and persist content only in the
  authorized acceptance transaction.
- External bots and provider-visible system authors never become invocation triggers.
  Their create callbacks create no admission, binding, access request, invocation
  batch, mailbox item, Session-running transition, wake dispatch, or cursor advancement.
- A later authorized human trigger includes those bot and system messages from provider
  history.
- An unauthorized human invocation retains only its metadata-only approval boundary. A
  later independent authorized human trigger still includes that unauthorized human's
  provider-visible message when it falls inside the unread history range.
- Remove `allow_bot_messages` from route persistence, service contracts, public API
  models, generated Python and TypeScript clients, Web management controls, and tests.
- Add a new forward-only contraction migration after the current migration head to
  remove the route column and related schema objects. Never modify executed migration
  `f17b4c8d6a21_add_external_channel_route_access_policy.py`. Preserve enough migration
  archive data for an exact tested downgrade of existing route rows without retaining a
  runtime compatibility path.

### Stable interfaces

- `ExternalChannelIngestionRequest` remains content-free.
- Metadata-only source identity contains provider key and position but no current
  revision.
- `_persist_history_message` or its replacement is called only for authorized batch
  acceptance.
- Context-only callbacks return an ignored terminal outcome without advancing the
  conversation position.
- Human block behavior remains fail-closed and does not authorize content persistence.
- Public route contracts no longer expose bot-trigger configuration.

### Validation

- Unit tests for pending access and selector commits assert no revision or content
  persistence.
- Real-PostgreSQL repository or service integration tests assert the metadata-only
  database state.
- Replay tests cover shared position before and after the original trigger.
- Slack and Discord tests prove bot/system callbacks do not advance positions and a
  later human trigger retains them in provider order.
- Slack and Discord tests prove an unauthorized human's pending invocation stores no
  content while a later authorized human trigger retains the first human's visible
  message as ordered context.
- Migration upgrade and downgrade tests cover existing routes with both historical bot
  policy values.
- Generated-client drift checks pass.
- Focused Python, TypeScript, and migration checks pass.

## Phase 2 — Canonical message contract and Discord fidelity

### Deliverables

- Remove current product lifecycle classification from external messages.
- Remove revision-kind classification from immutable external-message snapshots.
- Drop `lifecycle` and `revision_kind` runtime database columns and their PostgreSQL enum
  types through a new migration after updating all consumers in the same phase.
- Before dropping those current product columns, copy every existing value into an
  immutable historical annotation relation keyed by the canonical message and revision.
  Store the archived values as bounded text, not runtime enums. The relation has no
  ingestion, mailbox, API, engine, or Web consumer; it exists only for lossless
  historical inspection and exact downgrade.
- Preserve immutable message revisions, deterministic revision keys, batch-item
  identities, already accepted transcript content, and the archived historical
  lifecycle/revision values without exposing edit/delete classification as current
  product behavior.
- Remove Slack and Discord edit/delete normalization as canonical message variants.
- Project edit/delete callbacks into a content-free lifecycle-observation request that
  uses the same conversation scope, coordination lock, and durable-position lookup as
  create-trigger admission but never reads provider history or persists message
  content. An observation at or before the durable position is discarded by that normal
  position filter. An observation after the durable position is ignored without
  advancing the position so a later valid human trigger can ingest the then-visible
  provider state.
- Prove every lifecycle observation creates no canonical message/revision mutation,
  batch/item, mailbox item, Session-running transition, wake, promoted event, or chat
  item.
- Remove lifecycle and revision-kind fields from repository projections, mailbox
  payloads, promoted events, API presentation, generated clients, Web components,
  stories, translations, and tests.
- Retain invocation versus context presentation because authorization provenance is
  separate from lifecycle status.
- Project bounded Discord embeds from provider history into canonical attachment
  metadata and include them in normalized size accounting.
- Preserve embed order, bounded text, links, fields, media metadata, and truncation
  indicators without persisting unbounded provider payloads.
- Carry embeds through invocation projection, mailbox payload, Session event promotion,
  model-visible rendering, and chat presentation where provider-native metadata is
  currently exposed.

### Stable interfaces

- External message identity remains resource plus provider message key and position.
- External revision identity remains immutable and content-derived without a lifecycle
  category.
- Historical annotations remain queryable by canonical message/revision identity but
  are not imported into runtime enums, domain DTOs, public APIs, mailbox payloads,
  Session events, or Web presentation.
- Invocation authorization remains `authorized_invocation` or context provenance.
- Discord embeds use a bounded provider-neutral representation under attachment
  metadata; raw Discord payloads are not retained.
- Previously accepted Session events are not rewritten or deleted.

### Validation

- Migration upgrade tests cover existing current, edited, and deleted rows without
  losing referenced revision or invocation-batch identities or their archived
  historical lifecycle/revision values. Downgrade restores the exact original column
  values and enum types from the annotations.
- Repository, mailbox, event, OpenAI/LiteLLM rendering, and Web tests compile without
  lifecycle or revision-kind fields.
- Slack and Discord edit/delete callback tests cover both at/before-cursor and
  post-cursor observations through the shared position boundary. They assert zero
  message/revision mutation, batch/item, mailbox, Session-running transition, wake,
  promoted event, and chat item; post-cursor observations additionally assert no cursor
  advancement.
- Discord history, ingestion, mailbox, engine, and E2E tests assert visible embed
  preservation and provider order.
- Full generated-client checks and affected TypeScript build pass.

## Phase 3 — Validation

### Deliverables

- Run the complete requirements-to-implementation matrix against the stable Phase 2
  stack.
- Extend deterministic provider fakes only where needed for bot/system context,
  metadata-only approval, edit/delete zero-artifact checks, and Discord embeds.
- Record commands, environment, results, failures, corrections, and sanitized evidence
  in a new supporting validation report.
- Compare every `channel-260729/REQ` acceptance criterion and each ADR decision directly
  with code and test evidence. Do not substitute current specs for Requirements.
- Correct implementation defects found during validation before the validation PR is
  opened and rebase downstream branches when an earlier phase must change.

### E2E matrix

| Scenario | Slack HTTP | Slack Socket | Discord Gateway |
| --- | --- | --- | --- |
| Pending access stores boundary but no provider content | Required | Required | Required |
| Allow before shared cursor passes trigger | Required | Required | Required |
| Allow after shared cursor passes trigger without rollback | Required | Required | Required |
| Bot/system callback produces no input and does not advance cursor | Required | Required | Required |
| Later human trigger includes bot/system context | Required | Required | Required |
| Unauthorized human pending invocation stores no content | Required | Required | Required |
| Later authorized human trigger includes unauthorized-human context | Required | Required | Required |
| Edit at/before cursor is discarded by the shared position filter | Required | Required | Required |
| Delete at/before cursor is discarded by the shared position filter | Required | Required | Required |
| Post-cursor edit/delete observation is zero-artifact and preserves the cursor | Required | Required | Required |
| Discord visible embeds reach Session input | Not applicable | Not applicable | Required |
| Duplicate/concurrent human trigger remains one batch and wake | Required | Required | Required |
| Redis and memory lock lanes preserve identical accepted input | Required | Required | Required |

### Evidence rules

- No credentials, raw callbacks, message bodies, provider IDs, attachment URLs, embed
  text, or production identifiers in reports or logs.
- Evidence may include categorical outcomes, counts, hashes of deterministic fixtures,
  timings, and fixture-owned synthetic identities.
- Live-provider credentials are optional and never required for mandatory CI.

### Required quality matrix

- Python formatting and Ruff
- Pyright
- Focused external-channel service, repository, mailbox, engine, API, and migration
  suites
- Complete `python/apps/azents` pytest
- Generated OpenAPI clients
- TypeScript formatting, lint, typecheck, affected tests, and build
- Provider fake and deterministic External Channel E2E
- Redis and in-memory conversation-lock contracts
- Documentation frontmatter and index validation
- `git diff --check`

## Phase 4 — Living-spec correction

### Deliverables

- Run `/spec-review` against the validated Phase 3 diff.
- Update current behavior in:
  - `docs/azents/spec/domain/external-channel.md`;
  - `docs/azents/spec/flow/external-channel-provider-ingress.md`;
  - `docs/azents/spec/flow/external-channel-authorization.md`;
  - `docs/azents/spec/flow/external-channel-lifecycle.md`;
  - `docs/azents/spec/flow/agent-execution-loop.md`;
  - `docs/azents/spec/flow/test-strategy-e2e-primary.md`; and
  - other files identified by `/spec-review`.
- Update `code_paths` and `last_verified_at` where the covered implementation changed.
- Correct or supersede the 2026-07-29 validation report's claims that:
  - pending approval retained no provider content;
  - provider-visible fidelity was complete;
  - edit/delete behavior was fully validated; and
  - route-disabled bot cursor advancement preserved visible context.
- Keep the implemented Requirements, accepted ADR, and implemented Design immutable.
- Record no new ADR unless validation discovers a genuinely new hard-to-reverse
  decision.

## Phase 5 — Cleanup

### Deliverables

- Remove this multi-phase implementation plan.
- Remove all `channel-260729-drift-remediation-phase-*` execution plans.
- Remove no Requirements, ADR, Design, validation evidence, current spec, migration, or
  code artifact.
- Verify documentation indexes through the normal pre-commit workflow.

## Data and migration strategy

All schema changes use new migrations based on the latest main revision.

Planned contractions:

- remove route-level bot-trigger configuration;
- remove message lifecycle classification; and
- remove revision-kind classification.

The route contraction is a new migration after the current head. It never edits
`f17b4c8d6a21_add_external_channel_route_access_policy.py`. Upgrade removes the current
column after archiving exact existing values for downgrade; downgrade restores the
column and each route's prior value without adding a runtime compatibility branch.

The message-contract contraction first creates an immutable historical annotation
relation, copies the existing lifecycle and revision-kind values as bounded text keyed
to their canonical owners, and then drops the runtime columns and enum types. Runtime
code does not map or consume the historical annotations. Upgrade tests prove the copy is
complete before contraction; downgrade recreates the enum types and columns, restores
the exact archived values, and then removes the annotation relation.

The migration must preserve:

- canonical message and revision primary keys;
- each message's current revision link;
- invocation-batch item revision links;
- promoted immutable Session transcript events; and
- lossless historical lifecycle and revision-kind values for existing records;
- foreign-key and uniqueness invariants.

The migration must not infer accepted input, create a conversation cursor, replay a
provider callback, or restore retired event or pending-context state. Upgrade tests use
representative existing current, edited, and deleted rows and prove that referenced
content and archived historical values remain readable after runtime classification
columns are removed.

## Public API and generated artifacts

Expected public contract removals:

- route `allow_bot_messages`;
- external-message lifecycle presentation; and
- external-message revision-kind presentation.

Historical annotation storage is intentionally absent from OpenAPI and generated
clients.

Approval response fields that currently require persisted provider content are removed
or replaced with metadata-only presentation in the same phase. No deprecated aliases
or legacy fallback fields are added.

OpenAPI source changes are followed by the repository's client-generation workflow.
Generated Python and TypeScript clients are never edited manually. Web consumers are
updated in the same phase as the generated contract.

## Rollout and compatibility

- Each stack phase must be reviewable and pass its focused checks.
- Schema and code changes that must deploy together remain in one implementation phase.
- No dual-write, dual-read, compatibility processor, or legacy API fallback is added.
- Migrations are forward-only and do not edit previously executed revisions.
- Repository work stops at PR creation and CI monitoring. No live infrastructure or
  database change is authorized by this plan.
- PRs are never merged without explicit requester approval for the specific merge.

## Phase checkpoints

Before opening each phase PR, record:

- completed behavior;
- changed interfaces;
- validation commands and results;
- independent review findings and re-review decision;
- remaining stack scope;
- relevant paths;
- migration or data risks;
- generated artifact status; and
- whether downstream branches require ordered rebase.

The full stack is created before waiting on CI. CI is monitored only after all planned
PRs exist, and every failure is investigated before the stack is reported ready.

## Known risks

- Metadata-only approval removes currently exposed provider text or permalink data from
  pending approval presentation unless it can be derived without durable content.
- Removing public route and message-presentation fields requires synchronized generated
  clients and Web consumers.
- PostgreSQL enum and column contraction must preserve all referenced revision rows.
- Bot/system context tests must distinguish callback trigger eligibility from provider
  history visibility.
- Discord embeds can be large or deeply nested, so projection needs strict count, field,
  string, and total-size bounds.
- Existing deterministic approval tests currently rely on pending source text and must
  be rewritten to assert metadata-only state rather than silently restoring content
  retention.

## Completion criteria

The remediation is complete only when:

1. every phase PR exists and has independent review evidence;
2. all required corrections are applied;
3. the stable final stack passes the full validation matrix;
4. current specs describe the validated behavior;
5. no plan document remains after the cleanup PR;
6. no current edit/delete or bot-trigger product contract remains, while pre-remediation
   lifecycle/revision values remain losslessly inspectable outside runtime behavior;
7. pending access and selector database state contains no provider content;
8. Discord embeds reach canonical Session input;
9. no legacy inbound inbox or compatibility path is restored; and
10. the stack remains unmerged until explicit requester approval.
