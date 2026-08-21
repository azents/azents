---
title: "E2E Primary Test Strategy"
created: 2026-05-13
tags: [testenv, qa, e2e, process]
spec_type: flow
owner: "@Hardtack"
touches_domains: []
code_paths:
  - .claude/skills/e2e-ci-optimization/**
  - .claude/skills/feature-design/SKILL.md
  - .claude/skills/ship-feature/SKILL.md
  - .github/actions/expose-github-runtime/**
  - .github/workflows/ci.yaml
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
last_verified_at: 2026-08-21
spec_version: 33
---

# E2E Primary Test Strategy

## Overview

azents product behavior verification uses E2E as primary layer. `testenv/azents` is not a runner wrapping E2E, but a support layer responsible for fixture readiness and prerequisite classification.

This spec defines boundaries connecting azents feature design, E2E location, fixture/prerequisite support, credential/prerequisite snapshot, and CI execution policy in current implementation.

## Layer Boundaries

| Layer | Responsibility | Prohibited |
| --- | --- | --- |
| `testenv/azents/e2e/` | pytest-based product behavior E2E. Primary verification location for API/WS/browser/user journey regression. | Do not wrap E2E with testenv fixture command. Do not create product state through direct DB writes. |
| `testenv/azents/fixtures/` | Prepare reusable product state readiness and verify with doctor. | Do not own E2E/feature QA plan instead. |
| `testenv/azents/contracts/` | Declare credential/prerequisite contract and safe metadata schema. | Do not output raw secrets or store them in snapshots. |
| `testenv/azents/support/` | Promote only helpers confirmed to be repeatedly used in E2E/fixture/prerequisite. | Do not preemptively commonize. |

Manual-only runbook, blocked placeholder, removed-feature residue check, legacy TC markdown, `run-tc`, verifier, and markdown bash fallback are not part of event azents verification path. Primary evidence for product behavior QA is E2E result, and it is not separated into long-term catalog files.

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

Fakes and test evidence never retain credentials, authorization headers, signatures,
callback URLs, raw payloads, visible message bodies, attachment names, attachment
bytes, or transient provider URLs. Production Discord remains on its real secure REST
and Gateway endpoints; `http`/`ws` are permitted only for the explicit deterministic
test origin with an explicit insecure-Gateway opt-in.

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

| Consumer | Missing/stale snapshot |
| --- | --- |
| required E2E | fail |
| optional/live E2E | skip summary |
| fixture/prerequisite diagnostic | structured prerequisite error |
| prepare command | environment prep failure |

E2E and fixture/prerequisite diagnostic read only snapshot during test and do not run doctor again.

E2E tests reproduce product behavior through user-facing UI, public/internal test APIs, slash commands, OAuth flow, or documented fixture/prerequisite setup. They must not insert, update, or delete product rows directly to manufacture feature state. Cleanup SQL is allowed only in explicitly scoped reset helpers, not inside feature scenario tests.

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

- Python lint/type/unit and other deterministic checks.
- Testenv support tests run `uv run pytest -vv ./src/support_tests` for behavior that
  requires no server, network listener, container, product image, browser, Runtime
  Provider, or external prerequisite.
- E2E execution profiles are owned by directories, not individual pytest markers.
  `src/tests/required/` owns all credential-free required product E2E and
  `src/tests/web/` owns browser, TLS gateway, and Web image E2E. Each directory has
  one `suite.toml`, and every test below that directory uses the same substrate.
- One planner discovers enabled suite directories and creates a dynamic matrix.
  It balances files only within a suite using the latest successful `main` timing
  baseline, with a deterministic source-based fallback. Required uses three lanes;
  Web uses one lane. Lanes are parallel partitions, not additional profiles.
- Each lane upgrades the shared database to the tested Server image revision through
  one bounded migration container before product services start. Public API, Admin API,
  and Engine Worker then start concurrently; their ordinary launchers retain the
  current-revision check without competing to own an upgrade.
- Pull-request required lanes reuse the base-main SHA snapshot for Server, Runtime
  Runner, and Docker Runtime Provider images whose complete build inputs are unchanged.
  Snapshot authentication, availability, pull, or local-tag failure falls back to the
  existing current-worktree BuildKit build for the affected image. Main pushes and
  changed image components always build the current worktree.
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
- Worktree-built Server, Runtime Runner, Docker Runtime Provider, Main Web, and
  Admin Web E2E images import image-specific BuildKit GitHub Actions cache scopes.
  Independent images for the selected CI suite build concurrently inside each lane;
  focused local runs retain lazy per-image builds unless they explicitly select a CI
  image-build profile.
  Only `main` push jobs export cache, with one existing lane owning each scope;
  pull request jobs import without exporting. E2E artifacts include safe per-image
  build timing metadata and Buildx cache disk usage, but never cache credentials or
  cache URLs. Testcontainers-managed Selenium remains an external image pull rather
  than an Actions-cached Docker archive.
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
- Web Surface E2E runs from `src/tests/web/` in its own suite lane.
- Web Surface journeys use a pinned remote Chromium container. Web images are built from the tested worktree, and TLS gateways reproduce production secure-cookie and path-routing behavior without external credentials.
- Optional Managed Runtime Web Surface E2E creates all product state through public/admin APIs,
  then uses the real Main Web and server projections to prove the Runtime-free new-Session guidance,
  Profile-backed Add Runtime confirmation, managed controls, aggregate-only destructive removal
  confirmation, and non-cancellable removal progress. The browser journey does not write directly
  to PostgreSQL or derive Runtime actions in test code.
- The stable `ci-python-e2e` required gate aggregates support tests, the planner,
  all enabled suite lanes, and the timing aggregator for the scopes selected by path
  filtering.
- Each executed required E2E lane uploads bounded observability artifacts even when
  pytest fails. The artifact contains JUnit XML, the complete pytest output, the
  slow-test report, and Docker process/storage diagnostics. Failed browser calls also
  capture a screenshot and page HTML when the WebDriver remains available.
- Same-repository pull requests receive one sticky E2E observability comment. The
  comment is updated in place and contains only bounded JUnit-derived counts, failed
  node IDs, slow-test timing, wall-clock pytest execution time per lane, lane job
  results, and a link to the workflow artifacts. Test execution jobs retain read-only
  permissions; only the dedicated comment job receives `pull-requests: write`. Fork
  pull requests remain read-only and skip comment publication.
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
