---
title: "Responsive Context-Preserving External Conversations Validation Report"
created: 2026-07-29
tags: [external-channel, slack, discord, validation, e2e, redis, testenv]
document_role: supporting
document_type: supporting-validation-report
snapshot_id: channel-260729
---

# Responsive Context-Preserving External Conversations Validation Report

## Scope and provenance

This report validates the implementation stacked through
`feature/channel-responsive-context-07-contraction-surfaces` against:

- [`channel-260729/REQ`](../requirements/channel-260729-responsive-context-preserving-conversations.md);
- [`channel-260729/ADR`](../adr/channel-260729-responsive-context-preserving-conversations.md);
- [`channel-260729/DESIGN`](channel-260729-responsive-context-preserving-conversations.md); and
- the Phase 6 execution plan in
  [`channel-260729-responsive-context-preserving-conversations-phase-6-final-validation.md`](../plans/channel-260729-responsive-context-preserving-conversations-phase-6-final-validation.md).

Validation covers the post-contraction implementation: typed synchronous provider
admission, provider-history reconstruction, durable conversation positions, immutable
invocation batches and mailbox input, Session wake intent, Redis and in-memory
coordination, approval replay, provider-control settlement, Slack HTTP and Socket Mode,
Discord interactions and Gateway ingress, provider-native Channel Work, and explicit
External Channel file transfer.

- Validation date: July 29, 2026 (KST).
- Validation branch: `feature/channel-responsive-context-08-validation`.
- Base branch: `feature/channel-responsive-context-07-contraction-surfaces`.
- Phase boundary: no living spec, Requirements implementation date, Design
  implementation date, accepted ADR, public API schema, generated client, TypeScript,
  migration, or live infrastructure change is included in this validation phase.

## Environment and prerequisites

| Component | Observed value |
| --- | --- |
| Operating system | Linux 6.8.0-136-generic x86_64 |
| Python | 3.14.6 |
| uv | 0.11.1 |
| Node.js | v24.18.0 |
| pnpm | 11.15.1 |
| Docker client/server | 28.5.2 / 28.5.2 |
| PostgreSQL | Docker/Testcontainers fixture, ready |
| Redis | `redis:7.4-alpine` Testcontainers fixture, ready |
| Slack/Discord providers | Credential-free deterministic fakes |
| Model provider | Strict deterministic OpenAI Responses proxy |
| Runtime provider | Locally bootstrapped System Docker Provider through trusted Admin/Public APIs |
| Product state setup | Public, Admin, provider, and Runtime APIs only; no direct product database writes |
| Live provider credentials | Not required and not used |

The deterministic prerequisite set was ready. PostgreSQL, Redis, Docker networking,
provider fakes, the Agent Worker, Discord Gateway Worker, and Docker Runtime Provider
all executed locally. The in-memory conversation-lock lane constructed no Redis client.

Optional live Slack and Discord verification was not requested and no live credential
snapshot was consumed. No live provider, deployment, migration, Kubernetes, ingress,
or production database mutation was performed.

## Commands and results

| Area | Command | Result |
| --- | --- | --- |
| Backend format | `cd python/apps/azents && uv run ruff format --check .` | Passed; 1,464 files already formatted after review remediation |
| Backend lint | `cd python/apps/azents && uv run ruff check .` | Passed after review remediation |
| Backend types | `cd python/apps/azents && uv run pyright` | Passed; 0 errors, 0 warnings |
| Backend complete suite | `cd python/apps/azents && uv run pytest` | Passed; 3,754 tests, 6 warnings |
| Redis and memory lock contract | `cd python/apps/azents && uv run pytest -q src/azents/services/external_channel/conversation_lock_test.py` | Passed after review remediation; 5 tests, 3 dependency deprecation warnings |
| Focused External Channel backend/API/repository suite | `cd python/apps/azents && uv run pytest -q src/azents/repos/external_channel src/azents/services/external_channel src/azents/api/public/external_channel/v1` | Passed; 521 tests, 5 warnings |
| Testenv format | `cd testenv/azents/e2e && uv run ruff format --check src/support/image_generation_openai_proxy.py src/support/slack_provider_fake.py src/tests/azents/public/test_external_channels.py src/tests/test_external_channel_file_proxy.py src/tests/test_slack_provider_fake.py` | Passed |
| Testenv lint | `cd testenv/azents/e2e && uv run ruff check src/support/image_generation_openai_proxy.py src/support/slack_provider_fake.py src/tests/azents/public/test_external_channels.py src/tests/test_external_channel_file_proxy.py src/tests/test_slack_provider_fake.py` | Passed |
| Testenv types | `cd testenv/azents/e2e && uv run pyright .` | Passed; 0 errors, 0 warnings |
| Provider fake/proxy contracts | `cd testenv/azents/e2e && uv run pytest -q src/tests/test_slack_provider_fake.py src/tests/test_discord_provider_fake.py src/tests/test_external_channel_progress_proxy.py src/tests/test_external_channel_file_proxy.py` | Passed; 53 tests, 2 warnings |
| Deterministic External Channel E2E | `cd testenv/azents/e2e && uv run pytest -vv -s -m "not runtime_provider and not live_external and not web_surface" src/tests/azents/public/test_external_channels.py` | Passed; 9 tests, 3 deselected, 2 warnings in 127.86 seconds |
| Runtime-provider External Channel E2E | `cd testenv/azents/e2e && uv run pytest -vv -s src/tests/azents/public/test_external_channels.py::test_provider_native_channel_work_progress_journey src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey` | Passed; 2 tests, 2 warnings in 53.85 seconds |
| Focused file-transfer E2E | `cd testenv/azents/e2e && uv run pytest -vv -s src/tests/azents/public/test_external_channels.py::test_external_channel_file_transfer_journey` | Passed; 1 test, 2 warnings in 53.33 seconds |
| Documentation index | `python scripts/gen_docs_index.py --docs-root docs/azents --project-name azents --check` | Passed |
| Documentation index tests | `python -m unittest scripts.tests.test_gen_docs_index` | Passed; 14 tests |
| Diff hygiene | `git diff --check` | Passed after review remediation and report update |
| PR 7 required CI | GitHub Actions for PR #1030 | Passed, including deterministic E2E, Runtime-provider E2E, Python, migrations, TypeScript, web-surface E2E, Docker builds, Helm, and pre-commit |

The reported warnings are existing dependency deprecations and one existing SQLAlchemy
cartesian-product warning. No validation assertion was skipped. The three deselected
External Channel E2E tests are the two separately executed `runtime_provider` journeys
and the separately owned `web_surface` journey.

## Deterministic transport and provider evidence

The deterministic External Channel E2E module passed these credential-free public-path
journeys:

1. Slack HTTP signed callback admission, duplicate callback convergence, unknown
   participant approval, idempotent Allow, immutable Session input, provider-control
   create/delete settlement, and App uninstall;
2. Slack configuration replacement and repeated disconnect;
3. Slack Multi App route/default management and terminal disconnect;
4. Slack selector deduplication and open-access route binding;
5. Slack Socket Mode durable acknowledgement followed by controlled
   `link_disabled` reconnect state without credential leakage;
6. Discord Single activation and signed interaction admission;
7. Discord Gateway message creation with eager thread provisioning, active binding,
   Session input, and content-free fake evidence;
8. Discord message-command selector and component handling; and
9. Discord Multi management and lifecycle behavior.

The Runtime-provider lane additionally passed:

- provider-native Channel Work discovery and retained Slack Plan rendering; and
- one 6 MiB inbound Slack file materialization, Runtime processing into two outputs,
  and ordered Slack external upload completion.

Provider evidence retains bounded operation names, request counts, acknowledgement
identities, file counts, aggregate byte counts, hashes of deterministic upload bodies,
and categorical outcomes only. It excludes bot/app tokens, signing secrets,
authorization headers, raw callbacks, visible message bodies, attachment names,
attachment bytes, private download URLs, upload URLs, and production identifiers.

## Primary behavior matrix

The provider transports are anchored by the public-path E2E journeys above. Shared
provider-neutral correctness is additionally exercised at the ingestion, repository,
and provider-adapter boundaries so the same synchronous service contract is verified
without duplicating every failure injection in three container journeys.

| Behavior | Deterministic evidence | Result |
| --- | --- | --- |
| Durable Session input precedes successful acknowledgement | Slack HTTP and Socket acknowledgement E2E; Discord Gateway binding/input E2E; transport admission tests | Passed |
| Provider thread is created or reused before acceptance and owns output | Discord eager-thread E2E; Slack/Discord parent and manual-thread transport tests; delivery tests | Passed |
| Bound continuation requires no new mention | Retained-resource transport ingestion and active-binding service tests | Passed |
| Manual thread is reused for first invocation | Slack and Discord manual-thread transport tests | Passed |
| Connected App/Bot output is excluded while eligible visible context remains | Slack/Discord history and author-filter tests; provider fake range contracts | Passed |
| Newest 20 eligible messages plus one leading omission reminder | Bounded history collector and ingestion-store tests | Passed |
| Duplicate/concurrent trigger creates one durable batch, mailbox input, and logical wake | Slack duplicate HTTP E2E; position, ingestion, wake-claim, and repository concurrency tests | Passed |
| Provider/database/broker failure preserves the normal position | Position compare-and-set, history failure, wake timeout, broker recovery, and provider failure tests | Passed |
| Approval Allow replays on both sides of position advancement | Slack/Discord replay tests plus Slack approval E2E | Passed |
| Edit/delete does not rewrite accepted Session input | Create-trigger-only ingestion, immutable revision/batch, and projection tests | Passed |
| Redis and memory coordination preserve accepted-input semantics | Five lock tests, real Redis replicas, independent memory instances, and fenced PostgreSQL position tests | Passed |
| Evidence and diagnostics remain bounded and content-free | Fake/proxy contract tests, E2E redaction assertions, and log review | Passed |

## Redis and memory coordination

The validation adds an explicit common accepted-input contract for two independent lock
instances:

- two process-local in-memory lock instances may both perform provider reads, while the
  simulated durable position guard converges them to one accepted result and one
  duplicate;
- two clients against one real Redis container serialize the same conversation scope and
  converge to the same durable result;
- owner-token fencing surfaces Redis unavailability instead of falling back to memory;
- the existing repository contract verifies locked conversation-position
  compare-and-set fencing; and
- no broker, Pub/Sub, or unrelated Redis ownership was changed.

Redis remains optional for External Channel conversation coordination. Correctness does
not depend on Redis persistence or high availability, and Redis lock failure remains a
retryable surfaced failure rather than an implicit backend switch.

## Failures found and corrections applied

Validation found two deterministic fixture defects and one static typing defect. All
were corrected and their invalidated lanes were rerun.

1. **Redis test client construction did not satisfy the installed Redis type surface.**
   The real-Redis contract directly constructed `Redis(host=..., port=...)`, which
   produced six Pyright `reportCallIssue` errors. The test now uses the repository
   `create_redis_client(redis://...)` factory, preserving the health-check and
   non-retry policy required by the production Redis convention. Whole-backend Pyright
   and the five lock tests pass.
2. **The file-transfer model fixture assumed deferred tools were already visible.**
   The first real model request contained the file marker, binding, and two locators but
   exposed Tool Search rather than `download_external_file` and `channel_action`. The
   strict proxy returned `503 no_fixture_match`. The fixture now models the actual
   progressive disclosure sequence: Tool Search activates the deferred file and
   publication tools, then download, Runtime processing, and final publication execute
   in order. Sanitized journal evidence records only match state, tool availability,
   locator count, stage, and bounded tool-result diagnostics.
3. **The Slack fake did not accept the Slack SDK upload-target encoding.**
   `slack_sdk.AsyncWebClient.files_getUploadURLExternal` sends `filename` and `length`
   as POST query parameters. The fake parsed JSON and form bodies only, returned
   `invalid_arguments`, and prevented the final Channel Action result. The fake now
   merges typed query parameters with the request body and has a regression test for
   the SDK-compatible shape. The complete 6 MiB file-transfer E2E then passed.

No production behavior defect was found by the completed backend, transport, provider,
Runtime, or deterministic E2E validation.

## Implementation-to-spec comparison

The implementation is internally consistent, but the current living specs still
contain the pre-cutover event-processor, hydration, pending-context, and activation
model. PR 9 must promote the current synchronous behavior. The accepted ADR remains
unchanged.

| Living spec | Current drift | Required PR 9 promotion |
| --- | --- | --- |
| `spec/domain/external-channel.md` | Still defines durable Event, canonical Message/Revision, hydration cursor/high-watermark, pending context, and `waiting_hydration` activation as current authority | Replace retired state with typed trigger boundaries, provider-history-as-content authority, conversation positions, invocation batches, mailbox items, wake intents, and retained connection/route/resource/binding/access/work/delivery authority |
| `spec/flow/external-channel-provider-ingress.md` | The `Asynchronous Processing` section still describes event claims, hydration pages, pending-context writes, reconciliation, and activation after terminal hydration | Document synchronous typed ingestion for normal Slack HTTP, Slack Socket, and Discord Gateway messages; provider I/O before the final transaction; atomic durable admission before acknowledgement; position compare-and-set; duplicate/retry outcomes; and direct lifecycle/revocation control handling |
| `spec/flow/external-channel-authorization.md` | Allow still releases stored pending revisions from a `waiting_hydration` binding into an InputBuffer | Document immutable typed access-request boundaries and Allow replay through the shared ingestion service, with provider-history reconstruction, current authority revalidation, one invocation batch/mailbox identity, and no persisted raw callback content |
| `spec/flow/external-channel-lifecycle.md` | Allow, archive, and restore sections still refer to waiting hydration and pending-context cleanup | Describe synchronous active binding admission, retained terminal authority, provider-control intents, and cleanup without legacy hydration/pending-context state |
| `spec/flow/external-channel-delivery.md` | Commit-before-provider-call behavior is largely aligned, but the post-contraction Worker-owned provider-control claim/final-settlement authority is not complete | Add claim/I/O/final-settlement separation, same-attempt authority revalidation under lock, conservative stale `attempting` to `unknown`, and no blind provider replay |
| `spec/flow/agent-execution-loop.md` | External Channel batch lowering is substantially aligned but does not fully describe the synchronous admission and wake-intent boundary | Add durable admission, Session running transition, broker dispatch/recovery, duplicate wake recovery, and current conversation-position ownership |
| `spec/flow/test-strategy-e2e-primary.md` | Required Runtime-provider coverage names progress but not the file-transfer journey or the Redis/memory conversation-lock matrix | Add the final Slack HTTP/Socket/Discord deterministic matrix, Runtime-provider file-transfer lane, sanitized evidence rules, and explicit Redis/no-Redis lock contracts |
| `spec/flow/file-exchange-storage.md` | Current provider-neutral locator, verified Runtime transfer, authority revalidation, settlement, and no-file-body persistence text matches the implementation | Verify and refresh metadata only; no semantic change is required |

No new hard-to-reverse decision was discovered. `channel-260729/ADR` remains the complete
accepted decision record and must not be edited.

## Scope and sanitization review

- No raw callback content was added to canonical triggers, access requests, evidence, or
  diagnostics.
- Provider history remains the canonical content source.
- Provider I/O remains outside final database transactions.
- Final provider-control settlement continues to lock and revalidate current authority
  and the same delivery attempt.
- Redis broker semantics, Redis lock failure semantics, and memory coordination remain
  unchanged outside the explicit tests.
- No compatibility fallback, legacy processor, hydration API, activation API, pending
  context, cutover-preflight service/CLI, or temporary gate was restored.
- No generated client was manually edited.
- No TypeScript or public API source changed in this phase.
- No living spec or implemented snapshot date is included in this phase.

## Operational boundary

The repository implementation and deterministic validation are ready for independent
review and PR 8 CI. This does not satisfy the external production checkpoint required
before contraction merge or deployment.

PR #1030 and later stack PRs remain merge- and deployment-ineligible until an explicitly
authorized operator has deployed the pre-contraction generation with gates, quiesced
message ingress, observed a successful zero-backlog preflight, deployed and re-enabled
the synchronous generation, recorded sanitized production evidence, and confirmed that
rollback to the legacy schema is no longer required. No such live action or evidence is
claimed by this report.

## Readiness

All locally available mandatory validation lanes passed. The validation branch is ready
for final documentation checks, independent read-only review, commit, PR creation,
reviewer request, and required GitHub Actions CI. Spec promotion remains isolated to PR
9, and implementation-plan removal remains isolated to PR 10.
