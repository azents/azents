---
title: "E2E Primary Test Strategy"
created: 2026-05-13
tags: [testenv, qa, e2e, process]
spec_type: flow
owner: "@Hardtack"
touches_domains: []
code_paths:
  - typescript/apps/azents-web/src/shared/model-options/model-option-editor.ts
  - typescript/apps/azents-web/src/shared/model-options/image-generation-config.ts
  - typescript/apps/azents-web/src/shared/toolkits/toolkit-config-projection.ts
  - python/apps/azents/src/azents/api/public/chat/v1/validation_audit_test.py
  - python/apps/azents/src/azents/api/public/toolkit/v1/validation_audit_test.py
  - python/apps/azents/src/azents/repos/toolkit/validation_audit_test.py
  - testenv/azents/fixtures/mock_mcp_server.py
  - typescript/apps/azents-web/src/features/agents/components/AgentForm.stories.tsx
  - typescript/apps/azents-web/src/features/agents/components/AgentMemorySettings.stories.tsx
  - typescript/apps/azents-web/src/features/agents/components/AgentToolkitManagementSection.stories.tsx
  - typescript/apps/azents-web/src/shared/model-options/components/ModelCatalogPicker.stories.tsx
  - typescript/apps/azents-web/src/shared/model-options/components/SelectableModelOptionsEditor.stories.tsx
  - typescript/apps/azents-web/src/features/llm-settings/components/WorkspaceModelSettingsCard.stories.tsx
  - typescript/apps/azents-web/src/shared/toolkits/components/ToolkitForm.stories.tsx
  - typescript/apps/azents-web/src/shared/model-options/image-generation-config.test.mts
  - typescript/apps/azents-web/src/shared/model-options/model-selection.test.mts
  - typescript/apps/azents-web/src/features/toolkits/toolkit-config-projection.test.mts
  - typescript/apps/azents-web/src/shared/toolkits/github-creation-completion.test.mts
  - typescript/apps/azents-web/src/features/agents/google-management-integration.test.mts
  - python/apps/azents/src/azents/api/public/toolkit/v1/github_user_creation_cancel_integration_test.py
  - typescript/apps/azents-web/src/features/toolkits/github-user-creation-state.test.mts
  - typescript/apps/azents-web/src/shared/toolkits/components/GitHubWizard.stories.tsx
  - typescript/apps/azents-web/src/features/agents/components/AgentRuntimeSettings.stories.tsx
  - typescript/apps/azents-web/src/features/chat/components/ChatSessionView.stories.tsx
  - typescript/apps/azents-web/src/features/chat/components/ToolCallCard.stories.tsx
  - typescript/apps/azents-web/.storybook/**
  - .claude/skills/ci-optimization/**
  - scripts/ci/**
  - python/apps/azents/src/azents/conftest.py
  - python/apps/azents/src/azents/testing/transaction_fixture.py
  - .github/actions/ci-test-observability/**
  - .claude/skills/technical-feature-design/SKILL.md
  - .claude/skills/ship-feature/SKILL.md
  - .github/actions/expose-github-runtime/**
  - .github/workflows/ci.yaml
  - .github/workflows/ios.yaml
  - swift/scripts/ios.sh
  - swift/scripts/simulator-diagnostics.sh
  - typescript/packages/azents-session-core/**
  - .github/workflows/e2e-duration-recheck.yaml
  - .github/workflows/snapshot.yaml
  - azents.Dockerfile
  - azents-e2e-server-overlay.Dockerfile
  - docs/azents/AGENTS.md
  - testenv/azents/AGENTS.md
  - testenv/azents/README.md
  - testenv/azents/contracts/**
  - testenv/azents/e2e/**
  - testenv/azents/testenv/bootstrap_runner.py
  - testenv/azents/testenv/prerequisite_*.py
  - testenv/azents/testenv/checks/**
  - testenv/azents/testenv/live/**
  - python/apps/azents/src/azents/api/testenv/**
  - python/apps/azents/src/azents/runtime/**
  - python/apps/azents-runtime-provider-docker/**
  - python/apps/azents-runtime-provider-kubernetes/**
  - python/apps/azents-runtime-runner/**
last_verified_at: 2026-10-29
spec_version: 87
---

# E2E Primary Test Strategy

## Typed Runtime Hook and Live Observations

Runtime Hook E2E helpers validate mock journal/request evidence at ingress and
consume immutable text/tool projections while retaining provider-owned opaque
extensions for diagnostics. Malformed consumed fields and HTTP failures remain
failures, not empty readiness observations. Session and Chat-write responses use
the generated SDK's native wire factory.

External Channel live observations likewise use the native live-response factory
after primitive wire serialization, preserving nested `JSONValue` conversion,
explicit nulls and opaque extension fields. Focused deterministic helper tests
cover these decoding boundaries; they do not replace assembled product E2E.

The synthetic GitHub validation proxy decodes scenario, OAuth, revocation, and
MCP control input into runtime-validated immutable operations before dispatch.
Malformed or unknown control fields are rejected without issuing credentials,
revoking tokens, or executing tools. MCP initialization metadata remains an
opaque extensible object, and omitted or null request IDs retain the fixture's
acknowledgement contract. In-process support tests cover these boundaries without
opening a listener; assembled GitHub SDK and browser journeys remain E2E-owned.

## Overview

azents product behavior verification uses E2E as primary layer. `testenv/azents` is not a runner wrapping E2E, but a support layer responsible for fixture readiness and prerequisite classification.

This spec defines boundaries connecting azents feature design, E2E location, fixture/prerequisite support, credential/prerequisite snapshot, and CI execution policy in current implementation.

## Layer Boundaries

| Layer                       | Responsibility                                                                                               | Prohibited                                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| `testenv/azents/e2e/`       | pytest-based product behavior E2E. Primary verification location for API/WS/browser/user journey regression. | Do not wrap E2E with testenv fixture command. Do not create product state through direct DB writes. |
| `testenv/azents/fixtures/`  | Prepare reusable product state readiness and verify with doctor.                                             | Do not own E2E/feature QA plan instead.                                                             |
| `testenv/azents/contracts/` | Declare credential/prerequisite contract and safe metadata schema.                                           | Do not output raw secrets or store them in snapshots.                                               |
| `testenv/azents/support/`   | Promote only helpers confirmed to be repeatedly used in E2E/fixture/prerequisite.                            | Do not preemptively commonize.                                                                      |

Manual-only runbook, blocked placeholder, removed-feature residue check, legacy TC markdown, `run-tc`, verifier, and markdown bash fallback are not part of event azents verification path. Primary evidence for product behavior QA is E2E result, and it is not separated into long-term catalog files.

Representative product journeys remain primary end-to-end evidence. Status-only,
identifier/default, duplicate-constraint, and pure projection/parser matrices use
focused API, repository, or unit contracts. Real component/container stories own
form editing, Cancel, dialog copy, and responsive geometry instead of repeating
those presentation permutations in server-backed browser journeys. Toolkit
lifecycle/scope/attachment and owner/member persistence flows remain in E2E,
along with Runtime Web navigation and service lifecycle evidence. Component
interaction passes do not establish accessibility conformance; accessibility
diagnostics remain separate evidence.

Admin System Settings follows the same ownership split: native component/controller
tests cover label presentation and unsaved drafts during query-only section changes.
The representative authenticated settings/redaction boundary, cross-Web authentication
and persisted retention-policy updates remain browser E2E responsibilities.

## Login Browser Readiness

The invalid-refresh-cookie login journey checks the email input's visibility
and enabled state in one synchronous browser script over the current document.
It returns only a Boolean observation, never a WebElement retained across
separate find/display/enabled commands while auth-driven navigation or hydration
can replace the document. A missing, hidden, transparent or disabled input is
not ready; unrelated WebDriver failures still propagate.

The journey retains its real invalid-cookie navigation, 20-second readiness
deadline and login URL assertion. Docker-free tests protect the single-command
observation boundary; actual browser E2E remains the product evidence.

## Browser Consumer and Navigation Lifetimes

The native Browser journey finishes real GUI input before opening its fresh raw
reconnection/revocation observer. The GUI consumes and acknowledges its own
frames during those interactions; an unrelated raw receiver is not left idle
with a filling queue. The fresh observer still proves a different attachment to
the same native target and must receive the actual logout authorization close.
Keepalive failure is not revocation evidence. Default ping/queue limits, the
revocation deadline, fresh-login preservation and stale-target rejection remain.

Runtime Web authentication/history journeys observe the current final document
with one synchronous script: exact destination, complete document, expected
visible ready marker. Only the specific WebDriver navigation-abort observation
means not-ready during document replacement; unrelated errors propagate. Click,
back, forward and login actions are never replayed. Both cookie modes, blocked
Next assets, fragment/history assertions and existing deadlines remain.

## Direct File Transfer Evidence

Required file smoke tests retain the pre-transfer upload/auth/size, Exchange
download/delete, image/file model-input, Workspace, and Runner journeys, adapted to
metadata prepare/direct PUT/finalize and authorized empty `302` GET. The original
five real RustFS primitive tests retain provider compatibility with small bodies.
The stack-added checksum/publication/retry/owner/manifest matrix, ticket-expiry wait,
streamed-copy duplicate, and dedicated native-browser file journeys are not recurring
required E2E.

Fast route/ASGI, mock-service, shared-S3, frontend transport/hash, and component tests
own those boundaries: JSON-only manifests, invalid bodies, authorization before
storage I/O, immutable/idempotent publication, native checksum/signature parameters,
GET TTL/disposition/cache/referrer, streaming cleanup, and Worker progress/cancellation.
Configured file-size boundaries use 15/16/17-byte unit bodies and metadata-only
128 MiB schema probes; model-budget checks keep available attachment metadata without
reading an ineligible original. API, Worker, and Workspace fixtures retain the lowering-
only 1 MiB testenv limit. The completed
128 MiB acceptance evidence is preserved in the
[large-file validation report](../../design/direct-file-transfer-large-file-validation-report-2026-09-30.md),
not executed in routine regression CI.
The bounded native-browser acceptance evidence remains in that report rather than
being duplicated in routine CI. Unit/component checks establish the native link and
redirect contract, not proof of browser-saved bytes. RustFS fixture CORS remains PUT-only:
download navigation and inline images are not cross-origin fetch APIs.

Evidence records safe statuses, byte counts, hashes, and synthetic filenames; it omits
capability URLs/query values, signed headers, object keys, credentials, and cookies.
Capability issuance is not download completion: only browser-saved bytes establish
browser completion. An existing strict network restriction E2E proves control-plane
admission/configuration only, not packet-level direct-storage reachability in a deployed
`proxy_required` or `no_network` Runtime. Operator rollout readiness and optional live
provider prerequisites must remain explicit rather than being inferred from local tests.

## Deterministic Provider Boundaries

Credential-free provider fakes model only the platform contract required by an E2E
journey. The Discord fake supplies REST authority/delivery responses, a signed
interaction relay, and Gateway HELLO, heartbeat, Identify, Resume, dispatch,
reconnect, invalid-session, and close-code behavior. It is controlled only through
bounded test endpoints and retains evidence limited to operation identifiers,
provider-safe metadata, acknowledgements, state transitions, delivery outcomes, file
count, and aggregate byte count.

The Slack and Discord fakes also provide bounded provider-history ranges, mixed author
types, omission boundaries, ordered failure and `Retry-After` sequences,
exact/history operation barriers, duplicate/concurrency controls, and transport
acknowledgement evidence for durable batched External Channel ingress. Evidence retains
request counts, lifecycle categories, positions, bounded barrier state, file counts,
aggregate byte counts, deterministic hashes, and canonical relative Azents Session
routes only.

Discord provider fakes publish sanitized delivery and operation evidence before callers
can observe controlled failure boundaries. Regression coverage synchronizes on
authoritative evidence publication and the observable boundary instead of using
sleeps.

The Discord automatic-title journey pauses its already-ready Engine Worker before
triggering the provider flow, waits for the exact targeted message-delivery barrier
and committed direct-thread delivery evidence, then resumes the Worker. The title
model request therefore begins only after the successful rename precondition exists,
without holding a model response against its stream watchdog. The deterministic
Gateway fixture may also shorten lease, renewal, and connection-discovery polling
together through a complete testenv-only override; production defaults remain
unchanged.

Fakes and test evidence never retain credentials, authorization headers, signatures,
callback URLs, raw payloads, visible message bodies, attachment names, attachment
bytes, or transient provider URLs. Production Discord remains on its real secure REST
and Gateway endpoints; `http`/`ws` are permitted only for the explicit deterministic
test origin with an explicit insecure-Gateway opt-in.

The prepared inference-profile response barrier and Discord Gateway location-binding
journey use a function-scoped ordinary model-stream Worker fixture. The Gateway
journey pauses that replacement until direct thread delivery commits, then resumes
it and verifies generated-title commit and exactly-once thread rename. Its model
calls use the existing bounded ordinary policy rather than the deliberately
shortened default fixture policy used for watchdog coverage; no policy values
are tuned per journey.
The fixture stops the original Worker without removing it, starts one
replacement with bounded ordinary stream deadlines, and waits for readiness.
Reached, queued input, explicit release, and durable turn markers establish
ordering. Teardown removes the replacement and restores the same original Worker,
its readiness, and log capture. Public/Admin services, database, bootstrap state,
and the default fast-watchdog policy remain unchanged.

### Historical Memory Deterministic Journey

The required Historical Memory public journey creates a Runtime-free Agent,
integration and source Sessions through product APIs. Its
credential-free provider fixture returns strict `{"summary": ...}` output
through the ordinary Lightweight summary SDK path, separately from foreground
model behavior. A second representative journey runs independent Team and two
personal consolidation chains through real inventory/source reads, draft write/
edit error recovery, exact coverage and host publication. Captured model inputs
and tool results prove scope isolation and Runtime absence. It verifies preparation, boundary context, live generic VFS
inspection, retained human settings, and source archive/restore/Memory-disable
effects without live provider credentials or direct product DB writes.

The isolated testenv `POST /scheduler/v1/historical-memory/sample`
endpoint accepts an aware sampling instant and exact Agent ID, then invokes
the real bounded discovery admission/due-source, preparation and consolidation
services. Sampling changes Stage 1 eligibility time only; consolidation retains
real database leases and absolute deadlines. It does not rewrite source activity, replace production real-time
semantics, bypass source authorization, or add a production configuration mode.
An outer bounded timeout, preparation's 110-second real deadline and ordinary
consolidation attempt limits bound fixture work. Unexpected errors propagate
instead of becoming successful fixture responses.

This product journey proves service admission, provider summary execution,
publication, and visible consumption; it does not claim Scheduler dispatch,
Job Runtime supervision/coalescing, or precise concurrent interleavings.
Focused backend integration tests own those boundaries, plus retry/capacity,
scope/access loss, source purge, and snapshot no-reselection cases. Settings
presentation is covered by component/container tests and Storybook; the current
Historical Storybook interaction asserts loaded read-only presentation while
Memory is disabled. Switching and pagination belong to component/container
coverage, not that interaction. Report-style scale/query-plan evidence remains
a one-time validation artifact rather than a permanent load suite.

## Local Bootstrap and Fixture Flow

Event local preparation flow:

```bash
cd testenv/azents
uv run testenv bootstrap local
uv run testenv fixture doctor <fixture-id> --json
uv run testenv fixture up <fixture-id> --json
```

`bootstrap local` prepares only non-secret `.env` defaults, Docker compose infra, current-worktree devserver, `fixture up devserver`, and doctor summary. It does not create external secrets, log into Tailscale/OAuth, write directly to product DB, or run E2E. If fixture is missing/stale, prepare it explicitly with guidance from `fixture doctor` / `fixture up` / `fixture reset`.

## Credential and Prerequisite Snapshot

Credential and prerequisite are separated.

- **credential** — whether secret/source exists.
- **prerequisite** — whether credential, external service state, and local callback/config combine into test-runnable state.

Prepare phase runs doctor and stores snapshot.

```bash
cd testenv/azents
uv run testenv prerequisite prepare --profile live --json
```

Current priority contracts are Bedrock AWS shared credentials and Browser/OAuth storage state.
Snapshot includes `generated_at`, `mode`, `max_age_seconds`, `contract_hash`,
`worktree_fingerprint`, `env_fingerprint`, `status`, `checks`, and `guidance`. CLI output and
snapshots record only safe metadata such as present/missing, profile, region, and source path; they
do not include secret values.

Agent Runtime live prerequisite is declared with Runtime provider/control contract. Contract snapshot is stored around checks/guidance, and live helper separately calculates safe metadata such as provider mode, provider id, Kubernetes/Docker availability, Helm availability, and Runtime namespace. Provider credential, runtime-control auth token, and token map literal are not included in snapshot/API/E2E evidence.

Consumer policy:

| Consumer                        | Missing/stale snapshot        |
| ------------------------------- | ----------------------------- |
| required E2E                    | fail                          |
| optional/live E2E               | skip summary                  |
| fixture/prerequisite diagnostic | structured prerequisite error |
| prepare command                 | environment prep failure      |

E2E and fixture/prerequisite diagnostic read only snapshot during test and do not run doctor again.

E2E tests reproduce product behavior through user-facing UI, public/internal test APIs, slash commands, OAuth flow, or documented fixture/prerequisite setup. They must not insert, update, or delete product rows directly to manufacture feature state. Cleanup SQL is allowed only in explicitly scoped reset helpers, not inside feature scenario tests.

E2E-first does not require every exact internal race permutation to become a browser or full-stack
cross-product. Required product-path E2E owns user-visible journeys and representative cross-boundary
integration through public API, Worker/provider execution, durable state, and browser presentation.
Complex UI state matrices, confirmation and error dialogs, copy, conditional controls,
and responsive component interactions are owned by frontend component and Storybook
interaction tests. Browser E2E retains only behavior that requires a real browser or
crosses independently deployed product boundaries; it does not repeat an exhaustive
component-presentation matrix.
The required TypeScript lane also executes `@azents/session-core` behavioral
contracts. These cover pure tool/history/mailbox projection and a consumer
composing the package's exported modules without a browser host. A source
dependency-boundary check and DOM-free typecheck protect the shared-core
boundary. This does not replace cross-boundary browser E2E or certify a native
application or device lifecycle.

The same existing TypeScript job executes azents-web's native Node contracts,
including production-hook ownership/publication/cancellation and browser-storage
decoding. Its artifact contains native JUnit, command elapsed time, exit status
and exact SHA/run/attempt identity, not invented pytest setup/call/teardown phases.
Analysis requires the artifact whenever the Web Node step is enabled and validates
the Node runner, finite positive duration and exit status. Missing or conflicting
execution evidence cannot qualify a performance sample, even with green workflow
metadata or JUnit.

That job also runs the explicit Runtime Settings, GitHub Wizard, Agent Toolkit
Management, Chat Session
View and Routine tool-card component portfolio through Storybook's Vitest Chromium integration, with one
browser worker. The story catalog remains available independently; only this
portfolio is CI contract evidence. Interaction obligations use actual story plays,
not names or render-only success. Native JUnit, finite command duration, exit status
and exact SHA/run/attempt identity are required under the `vitest-browser` runner.
Missing, empty, skipped or failed component results fail the producer, and missing
native evidence cannot qualify analysis. No synthetic pytest phases are emitted.

The GitHub browser journeys retain saved Workspace popup authorization plus new
Agent same-context publication. The repeated cancellation-only OAuth journey is
owned by the actual Agent management Close/publication-guard component plays,
production management and wizard hooks, and a scoped HTTP/service/PostgreSQL
contract. The latter rejects another user, Session, Workspace or Agent, then proves
DELETE 204, candidate GET 404 and an empty Agent Toolkit inventory despite provider
cleanup failure. Wizard-hook contracts retain exact-attempt cancellation and
Session storage clearing. The component producer selects these management plays
explicitly; render-only stories do not replace the removed journey. The Workspace
new-publication ownership branch uses the production-hook and backend contracts
rather than repeating the OAuth journey. Runtime browser coverage retains initial
settings and Session metrics, stopped-state metrics, real lifecycle/storage
postconditions and mobile interactions without an extra unchanged running-state
settings/Session round-trip. Colocated confirmation/cancellation story plays
provide local interaction evidence; until a CI producer executes them, they are
not replacements for the retained browser checks.

Required repository, service, and Worker integration tests own exact interleavings whose authority is
PostgreSQL CAS, generation fencing, ownership recovery, transaction rollback, or stale-completion
ordering. Those tests must exercise production repositories and execution owners with explicit
barriers or authoritative state; pure mock reimplementations and fixed-sleep ordering are not
acceptance evidence. Each feature Design maps every required scenario to one primary required CI
owner and keeps live-provider tests diagnostic only.

Model quota fallback follows this allocation. Credential-free API/browser E2E verifies clean
candidate-chain consumption, a real quota-to-fallback response, immutable route provenance, and
one desktop transient fallback presentation that disappears after terminal completion. A colocated
mobile Storybook interaction verifies the responsive presentation and absence of availability
controls without repeating the full provider journey. Public availability and reservation contracts
remain covered by the API E2E; their internal health, generation-fencing, half-open claims,
reservation races, operation handover, compaction/title ordering, and Redis-empty recovery use
deterministic production repository/Worker integration tests.

Scheduled Task required E2E creates Workspace, Agent, Runtime, Session, and Task
state through Public/Admin APIs and generated clients. A credential-free
testenv-only Scheduler route on the existing Admin E2E server accepts one
timezone-aware instant and executes one bounded due-dispatch pass. The route is
mounted only when `AZ_TESTENV_API_ENABLED` is explicitly set. This avoids wall-clock
waiting, direct product database mutation, production Scheduler configuration
changes, and another suite-level service startup.

Scheduled Task E2E is intentionally limited to two focused user journeys:

1. create one Session-only one-time Task, read it through generated-client list and
   get, then delete it through the same public API;
2. create one Session-only Task due at the exact controlled instant, dispatch it
   through the ordinary Mailbox and Worker path, observe its durable terminal
   Session result, and verify automatic one-time deletion.

Schedule validation and authorization variants, recurring cursor and coalescing,
pre-start and post-start lifecycle races, provider registration and publication,
Slack and Discord exact-thread behavior, provider failure/no-replay, Session and
Binding cleanup, Web state projection, and compaction ordering and sanitization are
covered by focused backend or frontend contract tests. They do not create a
provider, lifecycle, compaction, or browser E2E cross-product.

## CI Policy

Always-on required CI does not depend on external credentials.

- Runtime lifecycle Web verification observes a single Start click's authoritative
  admission (advanced desired generation and target `running`) separately from usable
  metrics. Admission uses the existing bounded UI wait and metrics consumes only
  the remainder of the original readiness budget. Browser ownership is observed
  during API-based polling so a retired browser fails at that boundary; an
  unadmitted action reports bounded lifecycle state without repeating the click.
- Recurring E2E optimization owns implementation through measured acceptance, not
  only candidate analysis. One cycle may combine compatible, separately explainable
  coverage-preserving changes in E2E scenarios, fixtures, provider fakes, support
  code, CI setup, or production code when one change cannot clear the required
  critical-path threshold. A below-threshold same-SHA measurement returns to
  implementation while another safe candidate remains, then restarts the
  two-successful-attempt measurement on the new SHA. Review test bodies for
  duplicate journeys, unnecessary checks and wrong-layer matrices alongside
  infrastructure costs. Every removed or relocated scenario must map to retained
  representative E2E or an executed narrower-layer test; render-only stories are
  not interaction evidence. The cycle cannot claim improvement by dropping
  behavioral coverage, weakening assertions, bypassing real failure or
  lifecycle boundaries, extending timeouts, or adding sleeps. Adding runners or other
  CI resources requires explicit approval and complete cost accounting.
- The existing Runner Python and TypeScript component jobs use the official HTTPS
  Ubuntu archive instead of the Azure Ubuntu mirror for browser system dependencies.
  This changes only
  the exact mirror URI, preserving suites, components and repository signing keys.
  GitHub-hosted sources that reference the exact
  `mirror+file:/etc/apt/apt-mirrors.txt` list are mapped directly to the same official
  archive without reading or rewriting arbitrary mirror lists. The selector requires
  an enabled official Ubuntu source after rewriting, so an unsupported layout cannot
  silently continue with zero selected sources. Already-selected official sources
  remain valid and idempotent.
  Chromium installation, Firefox system dependencies, and pinned Camoufox/model
  installation remain ordered, mandatory steps with separate timings. The component
  job still runs the unchanged Playwright Chromium dependency installer and complete
  selected component portfolio; no dependency, browser engine or native test is skipped.
- Active CI optimization failures require diagnosis and repair rather than stopping
  at a failure report. When an experiment ends failed, rejected or inconclusive,
  durable reports retain its evidence; the unsuccessful PR is closed and its remote
  branch is deleted. Its clean owned worktree is removed, or explicitly reassigned
  to new active work, before the local experiment branch is deleted. Dirty, foreign
  and unknown worktrees remain protected, and actual cleanup blockers are reported.
  Draft status, future candidates, noisy evidence and approval blockers do not
  justify retaining a terminally unsuccessful experiment PR.
- Enabled E2E lanes consume the exact images built and smoke-tested by the existing
  Docker build matrix in the same workflow attempt. The Docker matrix is enabled
  whenever either E2E suite is enabled, including test-only changes. Consumers wait
  for its success; no extra job, matrix entry, registry publication, snapshot wait,
  or fallback rebuild is introduced. Required lanes consume Server, Runtime Runner,
  and Docker Runtime Provider; Web additionally consumes Main Web and Admin Web.
  Both producer and consumer check out the tested head SHA rather than the synthetic
  pull-request merge commit.
  The Runtime Runner producer imports content-addressed BuildKit layers from the
  existing Snapshot-owned `azents-e2e-v1-azents-runtime-runner` GHA scope. CI does
  not export this cache or add a cache writer. A cache miss uses the same ordinary
  build, and hits retain the exact checkout, Dockerfile, load, smoke and immutable
  image export; a cache never selects an old image tag or bypasses artifact checks.
  Each selected producer saves its inspected immutable Docker image ID, compresses
  once with zstd level 3 and one compression worker, hashes the archive and uploads
  an image-specific artifact bound to repository,
  tested SHA, run ID and attempt. Consumers validate the entire exact portfolio,
  receipt fields, non-symlink files, archive sizes and SHA256 hashes before loading
  any image. Two bounded import slots overlap independent archive loads on the same
  runner, without changing pytest workers or runner allocation. Every started import
  is drained even on another import's failure. Loaded IDs and the assigned local
  tags must match all receipts before environment variables are published.
  Missing, stale, duplicate, partial, corrupt
  or unexpected artifacts fail closed; they never select a local image rebuild.
  Existing fixture health, failure propagation, lifecycle ownership and final drain
  remain authoritative. Prepared-image worker plans explicitly record zero builds.
  Lane artifacts retain receipts, verification, per-image and total load durations.
  Before import, one preparation owner overlaps exact same-run artifact downloads
  through two bounded exact-name GitHub CLI download slots with pulls of the five
  existing public prerequisite images. Both tasks, every download and every
  prerequisite pull are joined before the owner returns.
  Missing downloads or failed pulls fail preparation without retry or fallback.
  No Selenium or additional image is added to this portfolio; ordinary fixture
  health/readiness and lifecycle behavior remain authoritative.
  Workflow step evidence separately measures export, upload, preparation, load and
  archive cleanup,
  while whole-workflow gate time and runner-seconds include the producer dependency.
  Preparation artifacts retain exact identity, every download/pull status and duration,
  plus same-clock download, prerequisite-owner and import boundaries to distinguish
  actual overlap from sums of nested work. They never contain credentials. Local
  optional snapshot preparation owns the shared public-image inventory while
  retaining its stdlib-only direct CLI and existing best-effort policy.
- Snapshot workflow dispatch keeps downstream publication enabled by default for
  compatibility. An explicit `dispatch_downstream: false` manual input builds and
  publishes immutable images without invoking the downstream deployment, allowing
  isolated same-SHA CI measurement without mutating live infrastructure. Snapshot
  publications on non-main refs with downstream dispatch disabled use OCI
  zstd-compressed layers to reduce transfer volume for isolated branch measurements.
  Main-ref publication and any downstream-dispatched publication retain the default
  gzip-compatible registry output.
- CI workflow dispatch compares changed scopes with the checked-out commit's first
  parent and enables the complete quality scope. Its E2E images come from the same
  run's Docker producers, exactly as on pull requests and main pushes.
- Python lint/type/unit and other deterministic checks.
- Testenv support tests run `uv run pytest -vv ./src/support_tests` for behavior that
  requires no server, network listener, container, product image, browser, Runtime
  Provider, or external prerequisite.
- E2E execution profiles are owned by directories, not individual pytest markers.
  `src/tests/required/` owns all credential-free required product E2E and
  `src/tests/web/` owns browser, TLS gateway, and Web image E2E. Each directory has
  one `suite.toml`, and every test below that directory uses the same substrate.
- One planner discovers enabled suite directories and creates a dynamic matrix.
  It balances files only within a suite using the per-file call-duration
  high-watermark from that suite's latest three successful timing samples, with a
  deterministic source-based fallback. A collector that inherits reusable scenarios
  and therefore has no local test bodies may declare an explicit positive fallback
  weight in source; observed timing still takes precedence. The first pull request run starts from the
  latest accessible rolling `main` history. Each successful `main` push attempt saves
  observed timing under a run-and-attempt-unique key, so a rerun cannot collide with
  an earlier attempt and later workflows can restore the newest rolling history. A
  successful internal pull request run saves its observed timing under the head
  commit SHA and an attempt-unique suffix, and later runs or attempts of that same SHA
  restore the newest SHA-specific rolling history before falling back to `main`.
  Fork pull requests do not publish timing caches. Required uses four lanes; Web uses
  one lane. Lanes are parallel partitions, not additional profiles.
  Large scenario families may expose multiple natural collection files backed by
  one reusable scenario module. When such a split replaces an existing collection
  file, the planner projects that file's historical per-test call timings onto the
  new collection files so the first plan retains representative weights.
  Deterministic External Channel collection uses
  `test_external_channel_management.py` for Slack HTTP admission, binding, and
  connection management; `test_external_channel_workspace_management.py` for
  multi-app workspace and mention-selector management;
  `test_external_channel_provider_progress.py` for provider-native progress;
  `test_external_channel_slack_socket.py` for Socket Mode;
  `test_external_channel_discord_gateway_binding.py` for Gateway location wait and
  binding; `test_external_channel_discord_configured_provisioning.py` for durable
  conversation provisioning; `test_external_channel_discord_unmentioned_activity.py`
  for unmentioned activity and typing recovery; and
  `test_external_channel_discord_journeys.py` for activation, commands, components,
  and lifecycle. These files collect reusable implementations from
  `external_channel_scenarios.py`. Subagent behavior uses
  `test_subagents.py` for lifecycle, wait, interrupt, and failure projection, while
  `test_subagent_capacity.py` collects mailbox and bounded-capacity scenarios from
  the reusable scenario class in `test_subagents.py`. Historical Subagent timings are
  projected by test name so the split is balanced on its first CI plan. External
  Channel shared Agent setup creates the required Workspace, model integration,
  Runtime Profile, and Agent records without eagerly
  starting every Agent Runtime. Journeys that execute Agent work rely on the product's
  on-demand Runtime lifecycle and retain their existing observable completion,
  recovery, delivery, and typing boundaries; management-only journeys avoid unrelated
  Runtime startup entirely.
  API-only upload/Exchange, saved model-profile, empty archived-Session and
  primary-first Team list scenarios likewise create isolated configured managed
  Agents without starting an unused Runtime or submitting an initialization turn.
  Their managed Runtime Profile, model catalog, primary Session and public
  authorization/storage/archive/scheduler assertions remain intact. Scenarios
  that submit messages or verify Runtime behavior retain their original
  Runtime preparation and execution path.
- Each lane upgrades the shared database to the tested Server image revision through
  one bounded migration container before product services start. Public API, Admin API,
  and Engine Worker then start concurrently through the launchers' underlying
  uvicorn or Python entrypoints, avoiding repeated schema queries after the explicit
  migration dependency has completed. Function-scoped External Channel Gateway
  processes use the same direct Python entrypoint after the already-migrated Public
  API dependency is ready. Production image defaults and shell launchers retain their
  current-revision validation.
- E2E image preparation and the independent PostgreSQL, RustFS, Valkey, deterministic
  model, GitHub validation, and Slack provider prerequisites start concurrently within
  one session-owned preparation lifetime. Selected image builds are submitted once;
  the ready Server image allows migration and core services to start while
  Runtime Runner, Docker Runtime Provider, and selected Main/Admin Web images
  continue building. Runtime consumers join their specific already-submitted image
  only when needed; a partial Server-ready view never triggers a duplicate build.
  The full selected-image join explicitly follows Runtime Provider readiness and
  gates actual Main/Admin Web image consumers. Browser API-only encryption and
  capture journeys require the backend/Runtime substrate but can execute while
  unused Main/Admin Web images prepare. Those images remain selected, submitted,
  failure-owned and drained; neither early nor late image failure can produce a
  successful lane. Deterministic fixture-graph tests prove browser-free body
  execution before a blocked Web image finishes, failure propagation at final
  drain, and the unchanged full gate for actual Web consumers.
  Real dependencies remain ordered: the OpenAI proxy starts only after the
  deterministic model service is healthy, migration waits for the Server image,
  PostgreSQL and storage, and product services still wait for migration. The
  session owner drains all selected builds before prerequisite teardown and
  surfaces unreported build failures even when a downstream setup failed before
  joining the full image view. Planned tags are not image readiness, and failed
  or cancelled builds are not rebuilt as a successful lazy fallback.
  Existing health checks and failure propagation remain authoritative.
  `core-prerequisite-timings.json` labels readiness as `infrastructure` until the
  Server image is actually ready, then as `server`, separately from the complete
  image-owner lifetime. The default local profile keeps lazy image preparation;
  a failed lazy Server build cannot publish Server readiness. Same-clock markers
  identify actual Server readiness and readiness boundaries for backend,
  full-image join and final drain. Per-image timing records retain actual
  monotonic start/end boundaries. Durations or nested fixture sums alone do not
  establish within-run overlap.
- Function-scoped local provider and proxy servers use a bounded short
  `serve_forever` polling interval so `shutdown()` observes termination promptly.
  Tests still complete both `shutdown()` and thread `join()` before releasing the
  fixture; elapsed delay is not used as the success condition.
- The required E2E aggregate downloads lane observability once. A failed download
  fails the aggregate job directly, including when partial artifact files were
  written; the required E2E gate therefore cannot accept incomplete observability.
  There is no automatic retry or wait for an external artifact service.
- Subagent required journeys reuse one immutable Workspace, model integration, and
  Runtime Profile. Five non-barrier journeys share one max-two Agent Runtime, while
  mailbox, timeout, interrupt, and active-overflow journeys share one max-three
  Runtime-hook Agent. Every journey retains an isolated root Session, and both Agent
  groups retain one team-primary journey. Barrier state is reset around every
  barrier-backed journey. The interrupted-child scenario blocks on that observable
  barrier instead of a wall-clock sleep.
- Local snapshot preparation remains an explicit developer tool, separate from
  gated CI image handoff. It can resolve compatible exact-current, predecessor or
  bounded first-parent images and build changed or unavailable images from the
  current worktree. Manual Snapshot runs on non-main refs publish immutable unique,
  SHA and run tags without moving `dev-main`; main-ref runs continue publishing it.
- Discord Single/Multi journeys use the public APIs and the deterministic provider
  fake; they do not create product rows directly. Focused fake contract tests cover
  signed interaction relay, Gateway lifecycle outcomes, nonce convergence, controlled
  REST failure outcomes, and multipart redaction.
- The deterministic External Channel module covers Slack HTTP, Slack Socket Mode,
  Discord HTTP interactions, and Discord Gateway durable admission; acknowledgement
  after content-free queue insertion and before provider history;
  first-one/later-ten batch limits; per-message mailbox cardinality and ordering;
  same-conversation cursor suppression; mixed success/retry/failure finalization;
  retry-tail and bounded `Retry-After`; post-commit wake failure and recovery;
  active-ingress diagnostics and Runtime shutdown drain;
  SDK-owned Slack endpoint replacement; Discord Identify-to-Resume recovery;
  provisioned or reused thread targeting; direct parent-channel targeting; bound continuation;
  mixed-author bounded history; duplicate
  convergence; access replay; Agent default and binding response-mode management;
  Slack `mention_only` early ignore without provider-history I/O; retained context on
  a later mention; `all_messages` continuation after a connected binding edit; Discord
  creation-time default copy; disconnected binding mutation rejection; first-mention
  setup with no pre-location Session/Binding/run; latest-source replacement; Multi
  provider-principal Agent selection; restricted setup Allow without Binding replay;
  Channel and Threads continuation; provider-native settings entry points; parent
  location/mode transitions; selected-Agent replacement and clear preserving thread
  Bindings; complete Slack manifest and Discord command reconciliation; versioned
  existing-Binding settings controls; and content-free evidence. Slack Socket and Discord
  Gateway journeys start the same provider-neutral External Channel gateway fixture,
  while the Agent Worker fixture remains responsible only for Session execution.
- The deterministic External Channel fixture explicitly enables provider participation;
  backend and Helm defaults remain disabled so the always-on lane is the only default
  environment that activates setup, parent-channel writes, and provider settings.
- Backend contract tests verify PostgreSQL first-one/later-ten claims, fenced Session
  leases, retry-tail movement, same-batch cursor views, final cursor CAS, atomic
  successful-subset mailbox admission, one post-batch wake, bounded failure logs,
  active diagnostics, producer recovery scans, and Redis-independent correctness.
- The required suite uses a locally bootstrapped and API-enrolled Docker Runtime
  Provider as suite substrate. It retains the two Tool Search Runtime Hooks scenarios,
  provider-native External Channel progress, Runtime Profile precedence/application/
  recreation, and the existing deterministic product journeys. Runtime Provider
  scenarios that were outside required CI are not retained.
- Local runs without prepared images retain lazy per-image builds, or concurrent
  selected-image preparation when explicitly choosing a CI image-build profile.
  Explicit local Buildx configuration can import image-specific Actions cache
  scopes; the Snapshot build matrix refreshes those scopes during publication.
  Gated E2E consumes prepared same-run images instead of invoking this build path.
  Artifacts never contain cache credentials or cache URLs. Testcontainers-managed
  Selenium remains an external image pull rather than a workflow image archive.
- Session working-folder coverage uses public API and the focused Docker Runtime Provider without
  direct product-database writes. Runtime-free roots prove nullable `none` bindings with no folder
  setup; managed roots prove `pending` to `bound` using current Runner evidence; permanent removal
  proves `pending`/`bound` to terminal `invalidated`; and re-add proves old `none`/`invalidated`
  contexts remain unusable while only a new root can bind. Project Browser and worktree lifecycle
  retain their existing bound-context checks. PostgreSQL migration coverage starts from the
  pre-feature schema, backfills existing Agents to `managed` and existing folder paths to `bound`,
  permits nullable paths for Runtime-free contexts, and validates the downgrade guard against
  unrepresentable optional-Runtime state.
- Deterministic Optional Managed Runtime E2E creates a Runtime-free Agent through public APIs,
  executes and persists a model-only turn, verifies no logical or physical Runtime appears, and
  confirms Runtime-backed Workspace projection remains unavailable.
- Interactive Runtime Terminal required E2E creates product state through Public/Admin
  APIs and uses the real Docker Runtime Provider, Runtime Control, Runner, and Linux
  PTY. Exactly two focused journeys verify the byte/control protocol, working
  directory, resize, Ctrl-C, bounded reattachment, explicit termination, and Runtime
  stop/start generation authority. Policy hierarchy, access revocation, Runtime-free
  denial, Runner capability mismatch, responsive presentation, and Web wiring remain
  in deterministic backend, protocol, component, and story coverage rather than
  independent full-stack journeys.
  Preparation waits for the current `can_open_or_attach` authority, including an
  ended Terminal whose final metadata remains retained. The fixture client batches
  cumulative output ACKs at 128 KiB, at logical output completion, or within a
  50-millisecond receive deadline. This stays below the live 256 KiB output window
  and avoids treating each small PTY chunk as a separate control message. Input,
  resize, replay, Ctrl-C, termination, and production rate limits retain their
  existing contracts.
- Web Surface E2E runs from `src/tests/web/` in its own suite lane.
  That existing job uses one isolated pytest worker with complete-file distribution
  and database, network, service, browser, Runtime, and temporary fixtures. Only one
  full product stack runs at a time on the hosted runner. Lane artifacts retain CPU
  topology, memory and before/after CPU, memory and I/O pressure for comparisons.
  Web plan files retain descending existing measured call weights (or declared
  source fallback) with path tie-breaking. The standard file scheduler keeps this
  plan order with `--no-loadscope-reorder` rather than re-sorting by testcase count;
  collection order within each file is unchanged. Required-suite lane files remain
  alphabetic and their execution remains serial. Worker restart is disabled, and the shared
  observer aborts unexpected worker death before unfinished tests are redistributed.
  Controller-only setup/call/teardown reports retain each testcase once. Automatic
  and explicitly reported fixture receipts share each worker's raw timing file;
  the controller validates and merges them after teardown.
  E2E-only startup, image, and browser-failure diagnostics are isolated under
  `workers/gwN/` within the existing lane artifact. Successful execution requires
  every configured worker's completed startup and raw fixture evidence, plus image
  receipts matching that worker's pre-build plan. Prepared images permit an explicit
  zero-local-build plan. Validated image receipts are published atomically into the
  existing aggregate file without replacing prior evidence; raw sources are retained.
  Native duration includes the worker and controller startup, collection, cleanup,
  and evidence merging. Fixture work can overlap and is not additive elapsed time.
  The same runner/job/matrix/image producers are retained. Runner-capacity
  observations are supplemental: unavailable tools or pressure files are recorded
  explicitly without skipping pytest or stopping Docker diagnostics and summaries.
- Required Brave Search journeys admit the five independent success Sessions before
  waiting for their persisted terminal run markers and idle projections. Every
  created Session is registered for draining before input admission; definite
  validation/auth rejection preserves the original error without awaiting a run
  that was never admitted. Cleanup continues through every admitted or ambiguous
  Session after a submission or drain failure.
  Tool Search routing, five endpoint results, Runtime capability, correlation,
  attachment bytes, vision continuation, credential failures, and text-only fallback
  assertions remain unchanged. Credential mutation and failure journeys remain serial.
- Web Surface journeys use a pinned remote Chromium container. Web images are built from the tested worktree, and TLS gateways reproduce production secure-cookie and path-routing behavior without external credentials.
- Runtime lifecycle Web checks observe the browser session during full-readiness
  polling. Start and Stop-to-Start each activate once, require a newer authoritative
  running generation, and share the original 120-second budget between admission
  and readiness or metrics. Timeout diagnostics distinguish missing admission from
  missing full readiness and retain bounded generation, target, convergence,
  availability, Provider resource and Runner state without credentials.
- Workspace Upload API E2E collects three public-API journeys against the real
  Docker Runtime Provider, Runtime Control, and HTTPS S3-compatible gateway:
  direct PUT followed by exact-byte download, destination conflict with explicit
  overwrite/retry without a second PUT for the retained source, and cancellation
  with no published destination. The fixture keeps trusted Runtime Control S3
  operations on the internal RustFS endpoint while exposing presigned PUT tickets
  through the HTTPS gateway. The gateway preserves method, path, query, signed
  headers, Host, and body. Browser-facing lifecycle states and actions are tested
  by colocated Storybook component interactions and deterministic frontend polling
  tests; browser E2E is not used to duplicate this API lifecycle.
- Optional Managed Runtime Web Surface E2E creates all product state through public/admin APIs,
  then uses the real Main Web and server projections to prove the Runtime-free new-Session guidance,
  Profile-backed Add Runtime confirmation, managed controls, aggregate-only destructive removal
  confirmation, and non-cancellable removal progress. The browser journey does not write directly
  to PostgreSQL or derive Runtime actions in test code.
- Runtime Web Gateway E2E starts the real Docker Runtime and launches a bounded
  loopback fixture application through the product Terminal API. It runs one
  representative shared-cookie browser identity flow through a local TLS wildcard
  edge, creates one Off Agent service through the generated Public client,
  turns it On through the authenticated service URL, and verifies stable secret-free
  URLs, current Agent-scoped projection, stale-revision rejection, expiration reset,
  direct Off control, browser upload digest and streamed download byte count,
  eight-asset fan-out, HTTP POST and error propagation, SSE, redirect handling, and
  WebSocket text, binary, ping/pong, and close behavior. A second Runtime Control
  replica accepts the Gateway session after the Runner has registered with the first
  replica, forcing the PostgreSQL Owner route and maximum-one-hop trusted relay path.
  The recurring file collects two tests: the shared-cookie full journey and maintenance
  preflight. Separate-domain ticket and authentication contracts remain in focused
  repository and Gateway settings tests. Active-exchange capacity, pre-body rejection,
  application/control buffer accounting, reservation release, and concurrent stream
  recovery remain in focused Gateway integration tests. The capacity backend is
  selectable between memory and Redis; Redis loss/recovery behavior stays within the
  same lightweight journey and does not make Redis a readiness dependency.
  Recurring defaults are 1 MiB transfer bodies, eight assets, and a 120-second
  browser-script deadline. The same collected journey accepts bounded
  `AZENTS_E2E_RUNTIME_WEB_TRANSFER_BYTES`,
  `AZENTS_E2E_RUNTIME_WEB_ASSET_COUNT`, and
  `AZENTS_E2E_RUNTIME_WEB_SCRIPT_TIMEOUT_SECONDS` overrides for an explicitly
  requested one-time run; CI does not set a heavy profile. Unauthenticated and
  malformed programmatic probes fail before application content. The fixture uses
  only generated clients, UI, Runtime Terminal, and public/admin APIs; it never
  writes product state directly to PostgreSQL.
- Runtime Web heavy-load verification is disposable evidence, not a recurring
  regression-test catalog. A feature, release, or incident that requires fresh load
  evidence raises the bounded environment values on the same lightweight journey,
  records a dated supporting report with commit/image identity, environment,
  workload, command, result, defects, and limits, and restores the low defaults
  afterward. It does not add a separate test node or heavy CI configuration. The
  current
  [2026-09-14 report](../../design/runtime-web-heavy-transport-load-test-report-2026-09-14.md)
  records one bounded 64 MiB/32 MiB local correctness and resource-pressure run; it
  is not a 1 GiB production throughput or latency benchmark.
- The stable `ci-python-e2e` required gate aggregates support tests, the planner,
  all enabled suite lanes, and the timing aggregator for the scopes selected by path
  filtering. It compares the maximum lane sum of pytest `call` phases with a complete
  recorded run for the PR base and fails at a twenty-percent increase or invalid
  candidate timing evidence. Missing base evidence is non-failing: an active
  exact-base CI workflow publishes a pending status and linked run, while an absent or
  completed base without compatible artifacts publishes a neutral successful status
  with an unavailable comparison. Candidate CI never waits for base completion.
  The CI aggregate evaluates and records the local duration verdict without posting
  a commit status. The existing independent reevaluation workflow owns external
  `ci-python-e2e` status publication. Publication failures remain visible in that
  workflow and cannot change a completed local duration verdict or its CI gate result;
  exact-base pending, terminal unavailable, regression, and invalid-evidence status
  meanings are unchanged.
  Every CI completion selects all open same-repository pull requests whose current
  head or base SHA matches the completed workflow head SHA. This includes dependent
  stacked pull requests with non-main bases and does not depend on run-associated PR
  metadata. Candidate completion and exact-base completion use the same evidence-only
  reevaluation path so ordering with initial sticky-comment publication converges.
  Candidate reevaluation excludes completed-but-cancelled workflow runs: their
  incomplete diagnostic artifacts cannot supersede valid same-head evidence.
  Genuine failed runs remain eligible for the existing fail-closed evidence checks;
  selection does not require a successful conclusion.
  Reevaluation workflows are serialized before evidence is read and publication
  begins. The helper checks current PR head/base identity before publishing status
  and again before replacing the duration block in the sticky observability comment.
  Same-repository pull requests receive updates; fork pull requests remain read-only.
  Retargeting and a 15-minute sweep retain equivalent
  fallback reevaluation without rerunning E2E. Fixture
  setup/teardown, Docker preparation, and full lane wall time remain diagnostic only.
- Each executed required E2E lane uploads bounded observability artifacts even when
  pytest fails. The artifact contains JUnit XML, the complete pytest output, the
  slow-test report, and Docker process/storage diagnostics. Failed browser calls also
  capture a screenshot and page HTML when the WebDriver remains available.
- The upload TLS gateway resolves its existing nginx image explicitly before
  Testcontainers construction. Cached local image IDs avoid registry access; an
  absent image is pulled once within the shared existing 300-second Docker budget,
  then its immutable local ID is used for container creation. Acquisition errors,
  invalid IDs and deadline exhaustion fail visibly instead of entering an implicit
  streamed pull. Safe gateway-image stage/outcome/timing evidence excludes raw
  registry output. TLS configuration, readiness and S3/browser assertions remain.
- General CI observability includes every Python matrix pytest project, migration
  tests, Docker-free support tests and Helm pytest, using the shared
  `scripts/ci/pytest_timing.py` plugin. It records only test identifiers, phases,
  durations, outcomes and fixture scope, not fixture values or captured logs.
  The observer binds its performance clock and output path at startup so application
  clock/environment mocks cannot consume mock values or redirect hook evidence.
  Existing E2E image/browser diagnostics and the E2E duration gate remain separate.
- Backend unit/integration pytest uses two processes inside the same existing CI
  job and runner. File-level distribution retains complete modules on one worker;
  each worker creates its own database/container and temporary-file fixtures.
  Each function-owned database transaction rolls back at test exit, while ORM
  contexts commit or roll back their own SQLAlchemy-managed savepoint. Explicit
  context commits, rollbacks, failures and cancellation cannot commit the outer
  test transaction. Other Python matrix projects and E2E lanes keep their existing
  execution model; no tests or assertions are excluded.
- Distributed test phases are recorded once by the controller. Each worker writes
  only safe fixture receipts to its own raw file. After worker and fixture teardown,
  the controller validates and merges these records into the usual timing evidence,
  retaining raw worker files in the artifact. Native command timing includes worker
  startup, repeated collection, teardown and this merge; additional worker/container
  preparation and memory are part of the measured cost. Phase totals aggregate
  per-test durations and can exceed elapsed wall time when intervals overlap.
- Worker restart is disabled explicitly. An unexpected worker death aborts the
  controller with a nonzero result before xdist redistributes the unfinished file;
  neither worker recreation nor automatic replay masks a crash. Ordinary assertion
  failures retain their normal reports and failing exit. Partial worker receipts
  remain diagnostic evidence, not a complete or successful test sample.
- Same-repository pull requests receive one sticky CI observability comment combining
  safe pytest counts, failed node IDs, phase/fixture timing and all CI job/step
  wall-clock durations, including TypeScript lint/typecheck/tests and Docker builds.
  Long details are bounded with full evidence linked in artifacts. Missing results
  remain unavailable rather than passing. Only the reporting job has PR write access;
  forks publish artifacts/job summaries but remain read-only and never post comments.
- Failed E2E calls also retain a bounded active-server diagnostic tail under the
  current worker's existing artifact directory, keyed by a hash of the testcase
  identity. This remains available when xdist workers have no terminal reporter,
  including API-only Browser failures without Selenium screenshots. Existing
  terminal diagnostics remain complete. Diagnostic filesystem errors are warnings
  and do not replace the original test failure or trigger retries.
- Whole-CI gate-completion elapsed time spans workflow creation to the last configured
  gate, including dependency scheduling and queues. Maximum job wall, aggregate
  runner job-seconds and E2E max-lane wall are distinct metrics. Reporting overhead is
  named separately. The `ci-optimization` Skill and shared collection/analysis/chart
  tools measure the Linux general CI workflow. iOS remains a separate quality
  workflow, excluded from speed statistics, daily charts and the same-SHA
  two-attempt measurement requirement. Its timing pair is not a prerequisite for
  Linux measurement completion; native failures remain explicit quality results.
  The iOS workflow checks out the pull request head (or main/manual SHA) and uses
  that same tested SHA in app-build and native diagnostic artifact names. A
  synthetic PR merge SHA is not substituted for the collector's head identity.
  Same-name native artifacts are explicitly replaced on a workflow repeat;
  complete immutable first-attempt evidence must be collected before repeating.
  Collected artifact ZIPs must match the SHA256 digest returned by the GitHub
  artifact API before extraction. Replay rechecks the saved ZIP digest and exact
  extracted file hashes against the authenticated archive, not only a locally
  generated manifest. The existing `e2e-duration-gate` verdict ZIP is retained
  with the same immutable identity, digest and attempt boundaries. A successful
  verdict upload requires its original artifact on collection and replay.
  When the current upload did not succeed, only a demonstrably older stable-name
  verdict is excluded; current verdicts retain every provenance check.
  Missing or malformed digests, missing archives, substituted
  bytes and unsafe or duplicate ZIP paths fail closed. Historical raw evidence
  remains preserved; incomplete evidence is not upgraded to verified success.
  Explicit JUnit testcase times, pytest phase/fixture numbers, image timing
  numbers and lane durations must be finite and nonnegative. Malformed or
  non-finite measurements fail parsing instead of becoming zero or valid
  analysis. An omitted optional JUnit testcase time retains its zero default;
  a supplied invalid time is not treated as omission.
  The Linux TypeScript producer selects an exact Node release, so native JUnit
  test identities do not vary with the runner image's cached minor release.
  Different reporter escaping is retained as incomparable source evidence,
  not silently normalized into an accepted same-SHA testcase match.
  Active server diagnostics are captured for fixture setup failures as well as
  test-call failures before fixture teardown removes the failing process.
  CoreSimulator runtime listing, device creation and native XCTest execution record
  timestamped start/end markers and original command exit status in
  `simulator-setup.log`, included by the existing always-upload diagnostic path.
  A stalled preparation command leaves a start marker before test logs exist.
  Command stdout remains unchanged for JSON/identifier consumers. The selected
  fresh simulator ID is passed directly to `xcodebuild test`, which owns startup
  and proves readiness through real app launch and UI assertions. A separate
  blocking `simctl bootstatus` preflight does not gate entry into XCTest.
  Native test/build checks, cleanup and the existing job deadline remain unchanged.
  Re-ingesting an identical workflow/run/attempt from another local collection
  directory is idempotent and retains the first stored source locator. Every
  other stored field, including opaque measurement/evidence extensions, must
  still match exactly; conflicting data fails without changing history.
  Same-SHA experiments require identical enabled scope, complete test evidence and
  two successful complete attempts. Testcase multisets are compared across numbered
  lanes within Required and Web separately because the planner may rebalance lane
  assignments; multiplicity, suite boundaries, general pytest producer identities,
  enabled lane jobs and original per-lane metrics are preserved. Historical
  E2E-only history is retained under
  its original scope, never relabeled as whole-CI performance. Daily charts show only
  the most recent 30 KST dates with mean/median/min–max/n and explicit failed/missing
  gaps. No branch-protection, failing duration threshold or test selection is changed.
- Web Surface path filtering includes backend/E2E dependencies, both web Dockerfiles, and the TypeScript workspace.
- testenv fixture/prerequisite unit, contract lint.

The maintained E2E suite does not contain external-credential or `live_external`
tests. Required Runtime Provider coverage creates its System Docker Provider
declaration through the trusted bootstrap source, enrolls it through the Admin and
Public HTTP APIs, and passes only the issued credential to the Provider process.

Runtime Execution Profile E2E creates policy state through Admin/Public APIs only. It verifies
typed unknown-field rejection, qualified engine-policy acceptance, hierarchy reductions and
expansion rejection, save versus explicit Apply, idempotent Apply, automatic restrictive
convergence, bounded audit/status projections, and response redaction. Bound Runtime application
still fails closed unless that Runtime's Provider has the required typed accepted contract. A Web
Surface journey first uses an actual server projection and may use server-shaped response fixtures
only for bounded presentation branches.

For features whose approved Design explicitly requires qualified Kubernetes execution-policy
coverage, that coverage is live evidence. Its prerequisite contract must distinguish unadvertised
capability from advertised-but-unenforced privileged engine, CNI, and storage capability.
Unadvertised capability may skip that live scenario; an advertised capability whose required
admission, isolation, network, or storage enforcement cannot be proven must fail. Missing
Docker/testcontainers or qualified-cluster prerequisites are unavailable evidence, never a local
live-PASS substitute. This general policy does not add a live-cluster or packet-qualification gate
to hierarchical Runtime network restriction, whose approved verification boundary is the
deterministic and focused coverage below.

Runtime Provider CI still validates direct workload hardening, Workspace persistence, Runtime
configuration compatibility, and fail-closed rejection of removed active containment payloads.

Hierarchical Runtime network-restriction E2E is deterministic and API-centered. It creates
infrastructure and Workspace Profile state through Admin/Public APIs, exercises the real Runtime
Control protocol with a bounded fake Kubernetes Provider participant, and verifies positive
capability compatibility, supported `proxy_required` and `no_network` composition, exact
desired/applied evidence matching, and bounded projection. It does not start a Kubernetes cluster,
create Kubernetes resources, execute packet probes, or claim packet enforcement. Expansion
rejection and other hierarchy-negative cases remain backend contract/service coverage. Kubernetes
resource and proxy behavior is covered separately by focused Provider/proxy unit, manifest,
protocol, lifecycle, trust, and forwarding tests.

## Feature and Ship Workflow Requirements

azents feature design must include `## Test Strategy` section. Minimum items are E2E primary plan, whether testenv fixture/prerequisite support is needed and why, fixture/product seed, credential contract, prerequisite snapshot, evidence format, CI execution policy, and live/optional skip/fail criteria.

`ship-feature` phase plan includes E2E primary verification matrix. If product behavior verification remains only as testenv support without E2E, an explicit exception is required. QA report separates verification goal, E2E evidence, and fixture/prerequisite evidence.

External substrate features such as Agent Runtime Provider are recorded in two layers.

- deterministic evidence: auth negative matrix, redaction assertion, prerequisite contract lint, diagnostic API shape, no-active-provider helper behavior, explicit skip/fail reason of Helm render test.
- live evidence: provider-enabled lifecycle, Runner-reported workspace path, persistence preservation across stop/restart, reset-only destructive behavior, reconnect/stale generation, provider liveness, Helm-enabled environment participation.

Local/PR environment without live substrate does not fake live PASS. Instead, separate prerequisite snapshot state and deterministic evidence in PR body and design QA record. If primary E2E substrate such as Browser runner or Docker/testcontainers is unavailable and product path cannot be executed, do not replace it with PASS. Track scenario, blocker category, observed error, expected verification target, and next action in GitHub Issue, and leave blocked evidence plus issue link in design QA record.

## Changelog

- **2026-10-15** (spec_version 87) — Added required TypeScript execution of
  the shared Session core's behavior and package-consumer contracts.

- **2026-10-09** (spec_version 86) — Remove stale-document login readiness
  races with an atomic current-document visibility/enabled observation.

- **2026-10-04** (spec_version 82) — Added isolated multi-turn consolidation
  product verification and production-service sampling with ordinary leases and
  deadlines; retained narrow backend ownership of exhaustive races/capacity.

- **2026-10-02** (spec_version 81) — Excluded cancelled candidate workflow
  artifacts from duration reevaluation without filtering genuine failed runs
  or changing validation thresholds and head/base publication guards.

- **2026-10-02** (spec_version 80) — Added credential-free Historical
  product-path evidence and explicit-time service sampling, distinguishing
  preparation/publication from separately tested Scheduler/Job Runtime dispatch.
- **2026-10-02** (spec_version 79) — Selected all same-repository PRs whose head
  or base matches a completed CI SHA, including dependents of non-main stacked bases.
- **2026-10-02** (spec_version 78) — Made missing base duration evidence
  non-failing, reserved pending for active exact-base CI, and synchronized guarded
  status plus sticky-comment reevaluation when either base or candidate CI completes.
- **2026-10-01** (spec_version 77) — Kept representative desktop quota-fallback and
  shared-cookie Runtime Web browser journeys, moved mobile presentation to a Storybook
  interaction, and assigned alternate authentication plus capacity edge cases to
  focused lower-layer tests.
- **2026-10-01** (spec_version 75) — Added base-relative duration gating,
  evidence-only base-change reevaluation, and compact collapsible comments.

- **2026-09-30** (spec_version 74) — Moved stack-added heavy file-transfer matrices
  and native-browser journeys out of required E2E into fast unit/component ownership,
  preserving pre-stack real-storage and product smoke boundaries.

- **2026-09-30** (spec_version 73) — Replaced recurring heavyweight file journeys
  with lowered, injected limits and small protocol bodies; retained one-time
  large-file evidence separately and fenced fixture-only download TLS handling.

- **2026-09-30** (spec_version 72) — Added real-storage/native-browser direct-file
  evidence boundaries, capability-safe artifacts, and strict-network proof limitations.

- **2026-09-29 (spec_version 71)** — Isolated explicit inference-profile response
  barriers from the fast-watchdog fixture without changing default timeout tests.
- **2026-09-24 (spec_version 70)** — Documented preservation of the
  exact-current snapshot SHA when parallel setup observability is appended.
- **2026-09-21 (spec_version 67)** — Preferred compatible exact-current-SHA
  snapshots for unchanged E2E image inputs before predecessor and ancestor
  candidates, preserving immediate fallback when the current publication is absent.
- **2026-09-20 (spec_version 66)** — Moved per-image BuildKit GitHub Actions
  cache exports from gated E2E lanes to the Snapshot workflow build matrix while
  retaining cache imports in gated lanes and avoiding an additional runner.
- **2026-09-18 (spec_version 65)** — Added the public-API Workspace Upload
  matrix and its HTTPS S3 gateway trust boundary: exact PUT/commit bytes,
  conflict-overwrite retry, cancellation without publication, Runtime Control
  internal storage access, and Docker Provider/Runner CA propagation. Browser
  lifecycle states are covered by component interactions and deterministic polling
  tests rather than duplicate browser E2E journeys.
- **2026-09-15** (spec_version 64) — Replaced Runtime Web approval-cycle E2E with
  Off-service URL activation, Agent-scoped service projection, reset revision
  fencing, and direct Off control.
- **2026-09-15** (spec_version 63) — Extended immutable snapshot reuse and
  prerequisite pre-pulls to every Web E2E image, reused the session Chromium across
  isolated Runtime Web scenarios, launched Chromium through a Web-suite-only session
  dependency before other Web fixtures, refreshed authoritative Runtime metrics
  instead of waiting for a stale UI polling cycle, reduced browser-wait polling only
  for selected non-Runtime browser journeys while retaining the same timeout bounds,
  started independent Runtime Web topology containers concurrently,
  and defined the full gated E2E critical path across every enabled suite lane.
- **2026-09-14** (spec_version 61) — Made recurring Runtime Web verification a
  four-test lightweight 1 MiB/eight-asset matrix with relay, hard-limit,
  maintenance, protocol, and optional Redis recovery coverage; added bounded
  environment overrides on the same journey; and made heavy-load runs disposable
  dated report evidence without a separate pytest node or heavy CI profile.
- **2026-09-13** (spec_version 60) — Defined E2E-first layered verification for model quota
  fallback: product-visible and representative cross-boundary E2E plus production
  repository/Worker integration tests for exact concurrency, fencing, recovery, and rollback
  interleavings.
- **2026-09-12** (spec_version 59) — Made manual CI dispatch classify required
  image changes against the checked-out commit's first parent, preventing stale
  predecessor snapshots from running newer E2E tests.
- **2026-09-12** (spec_version 58) — Made successful `main` push timing-history
- **2026-09-13** (spec_version 59) — Defined E2E-first layered verification: product-visible and
  representative cross-boundary E2E plus required production repository/Worker integration tests
  for exact concurrency, fencing, recovery, and rollback interleavings.
- **2026-09-12** (spec_version 58) — Made successful `main` push timing-history
  cache saves unique per workflow attempt while retaining SHA-scoped pull request
  history and rolling `main` restore fallback.
- **2026-09-11** (spec_version 57) — Overlapped exact-SHA snapshot preparation
  with lane dependency setup through a durable fail-closed handoff, used
  zstd-compressed registry output for isolated non-main snapshot publications,
  and started already-migrated E2E services through their direct process
  entrypoints.
- **2026-09-11** (spec_version 56) — Allowed same-repository pull requests to
  consume already-published exact-current-SHA image snapshots with immediate
  current-worktree fallback, and prevented non-main manual Snapshot runs from
  moving the shared `dev-main` package tag.
- **2026-09-11** (spec_version 55) — Split the remaining External Channel management
  collector into connection, workspace, and provider-progress files, projected both
  legacy and immediately prior timing paths, and overlapped best-effort prerequisite
  image pulls with immutable snapshot preparation while preserving fixture fallback.
- **2026-09-11** (spec_version 54) — Split Subagent lifecycle and capacity collectors,
  projected historical per-test timings, and added finite explicit source fallback
  weights for indirectly collected scenarios.
- **2026-09-10** (spec_version 53) — Removed eager Runtime startup from shared
  deterministic External Channel Agent setup. Runtime-bearing journeys retain
  product-owned on-demand startup and observable completion boundaries, while
  management-only journeys no longer prepare unrelated Runtimes.
- **2026-09-10** (spec_version 52) — Replaced single-sample E2E lane weights with
  per-file high-watermarks from each suite's latest three successful timing samples
  while preserving deterministic fallback, same-SHA cache precedence, suite
  ownership, lane count, and file coverage.
- **2026-09-10** (spec_version 51) — Added dependency-compatible Server snapshot
  source overlays for application-source-only pull request changes, with complete
  application replacement, exact-current-snapshot precedence, deterministic
  full-build fallback, and explicit build-mode observability.
- **2026-09-10** (spec_version 50) — Added protocol-observable Discord automatic-title
  synchronization and the complete testenv-only Gateway timing override while
  preserving production defaults and journey assertions.
- **2026-09-08** (spec_version 48) — Split the Discord provisioning collector into
  independently planned Gateway binding, configured provisioning, and unmentioned
  activity journeys while preserving historical timing projection and coverage.
- **2026-09-02** (spec_version 43) — Added two focused real-Docker Runtime
  Terminal journeys for protocol behavior and Runtime lifecycle authority while
  retaining policy and Web presentation coverage in deterministic lower layers.
- **2026-09-01** (spec_version 42) — Reused compatible Subagent E2E Workspace and
  Agent Runtime setup across isolated journey Sessions, and replaced the interrupted
  child wall-clock sleep with the existing explicit Runtime-hook barrier.
- **2026-08-30** (spec_version 40) — Added bounded compatible-ancestor fallback
  for unchanged required E2E images when an exact predecessor snapshot is
  unavailable, while preserving direct successes, immutable Git-tree validation,
  artifact evidence, and current-worktree builds for changed or unresolved images.
- **2026-08-28** (spec_version 39) — Made sanitized Discord failure evidence
  authoritative before callers can observe controlled failure boundaries.
- **2026-08-27** (spec_version 38) — Made configured Discord REST failure
  delivery and operation evidence atomic and authoritative before HTTP, connection,
  or timeout outcomes become observable.
- **2026-08-27** (spec_version 37) — Required recurring E2E optimization to treat
  test and fixture code as first-class implementation surfaces, combine compatible
  and separately explainable coverage-preserving changes when needed, and continue
  new-SHA same-SHA measurement cycles until acceptance or feasible-candidate
  exhaustion.
- **2026-08-25** (spec_version 36) — Increased the required E2E suite from three
  parallel lanes to four while preserving one execution profile, deterministic
  file coverage, timeout policy, and single-lane cache-write ownership.
- **2026-08-22** (spec_version 34) — Split deterministic External Channel
  collection into natural scenario files for file-level required-lane balancing
  and added historical per-test timing projection for the first post-split plan.
- **2026-08-20** (spec_version 32) — Added one migration owner followed by concurrent
  Public API, Admin API, and Engine Worker startup in each E2E lane, and linked the
  recurring E2E CI optimization skill to the current test strategy.
- **2026-08-17** (spec_version 30) — Added focused Scheduled Task
  generated-client creation/readback and due-now execution journeys, moved
  provider, lifecycle, recurrence, Web, and compaction combinations to focused
  contract tests, and retained deterministic dispatch on the existing E2E server.

- **2026-08-13** — v29. Replaced marker-selected deterministic, focused Runtime
  Provider, Web Surface, and unused live groupings with folder-owned `required` and
  `web` suites, timing-balanced planner lanes, and one dynamic E2E runner matrix.
- **2026-08-13** — v28. Added deterministic API-created hierarchical network-restriction
  control-plane coverage, explicitly separated from Kubernetes Provider/proxy unit, manifest,
  protocol, lifecycle, trust, and forwarding validation and from any packet-enforcement claim.
- **2026-08-10** — v26. Added Optional Managed Runtime deterministic, focused Docker Provider, and
  Web Surface E2E policy, including Runtime-free model execution and UI guidance, explicit add,
  lazy start, Provider-outage removal, privacy-safe progress, exact reconnect acknowledgement,
  higher-generation re-add, destructive browser confirmation, and nullable Session binding
  migration/invalidation evidence.

- **2026-08-10** — v25. Added deterministic active-ingress barriers, ordered
  `Retry-After` controls, durable acknowledgement-before-history evidence,
  batching/cursor/mailbox/retry/wake diagnostics, and local prerequisite-failure
  handling for the batched External Channel ingress matrix.
- **2026-08-11** — v27. Removed AppArmor/bwrap containment prerequisites and the dedicated
  Kubernetes containment lane; retained direct Runtime Provider product journeys and contract
  rejection coverage.
- **2026-08-09** — v24. Added enforcing-AppArmor Docker Runtime Provider coverage and the required
  disposable kind Kubernetes containment lane with bounded evidence, fail-closed prerequisites,
  qualification, security boundaries, persistence, ephemeral clearing, and direct rollback.
- **2026-08-04** — v21. Added deterministic Session working-folder public and
  Docker Runtime E2E coverage plus PostgreSQL expand/backfill/contract migration
  evidence, including archive symlink-boundary and restore behavior.
- **2026-08-05** — v22. Moved server-free testenv support verification into a
  Docker-free unit job while retaining server, container, image, and product journeys
  in the existing E2E lanes.
- **2026-08-03** — v20. Added required-lane JUnit, pytest output, slow-test,
  Docker diagnostic, and browser failure artifacts plus the same-repository sticky PR
  observability summary.
- **2026-08-03** — v19. Updated Runtime Provider live evidence to verify the
  current Runner-reported Agent Workspace path rather than Provider metadata.
- **2026-08-02** — v18. Added deterministic public-boundary verification for
  first-mention setup absence, original-trigger continuation, parent/thread behavior,
  provider-native settings, selected-Agent lifecycle transitions, provider command
  contracts, versioned existing-Binding controls, and bounded secret-free fake
  evidence.
- **2026-08-01** — v17. Added public-API and Web Surface verification for Agent and
  binding response modes, including Slack mention gating/context preservation,
  all-messages continuation, Discord creation-time copy, and disconnected mutation
  rejection.
- **2026-07-31** — v16. Allowed fake-provider evidence to retain only the canonical
  relative Azents Session route needed to verify provider links against public
  Session list/detail projections.
- **2026-07-31** — v15. Replaced the Discord-only gateway fixture and Worker-owned
  Slack Socket lifecycle with one provider-neutral External Channel gateway fixture.
- **2026-07-31** — v14. Added deterministic Slack Socket endpoint-replacement and
  Discord Gateway Resume verification through provider fakes and public product paths.
- **2026-07-30** — v13. Added the post-contraction Slack HTTP, Slack Socket,
  Discord Gateway, Redis/memory coordination, provider-history, sanitized evidence,
  and Runtime file-transfer validation matrix.
- **2026-07-26** — v11. Added Runtime Execution Profile API-managed E2E, safe policy-evidence redaction, explicit Apply/convergence coverage, and qualified Kubernetes fail/skip requirements.
- **2026-07-26** — v10. Added the credential-free Discord REST/Gateway fake,
  signed interaction relay, provider-evidence redaction contract, and public-API
  Single/Multi deterministic E2E boundary.
- **2026-07-23** — v9. Added the credential-free focused Runtime Provider lane and its bootstrap/enrollment boundary to required E2E CI.
- **2026-07-17** — v8. Split real-browser journeys into the parallel Web Surface E2E lane while preserving the stable required E2E gate.
- **2026-07-13** — v7. Added deterministic containerized Chromium journeys and worktree-built web images to the always-on E2E policy.
- **2026-07-08** — v6. Added the no-direct-DB-write E2E scenario boundary used by subagent validation.

## Related Records

- testenv operational guide: [`../../../testenv/azents/AGENTS.md`](../../../../testenv/azents/AGENTS.md)
