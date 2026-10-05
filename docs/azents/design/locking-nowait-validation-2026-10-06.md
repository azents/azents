---
title: "Removal-First Lock Validation Register"
created: 2026-10-06
tags: [backend, concurrency, reliability, memory, authorization]
document_role: supporting
document_type: supporting-qa
snapshot_id: locking-261005
---

# Removal-First Lock Validation Register

This supporting record accounts for each nonwaiting acquisition at baseline
`ae5fffc89ac30fcc58baaf2ac0a4f3f6dc8db03c`. Line numbers below refer to that
baseline, not the final source layout. It implements the confirmed outcome in
[locking-261005/REQ](../requirements/locking-261005-minimize-nowait.md) through
[locking-261005/DESIGN](locking-261005-minimize-nowait.md); it creates no new
policy or authority. Prior implemented snapshots remain unchanged.

All repository paths in the table are relative to
`python/apps/azents/src/azents/repos/`.

## Individual Removal Register

| ID | Baseline declaration | Exact participant | Replacement |
| --- | --- | --- | --- |
| S01 | `agent_session/__init__.py:1240` | Source/target Session | Existing NO KEY UPDATE waiting lock; complete owning operation recovery |
| S02 | `agent_session/__init__.py:1635` | Root membership node | Waiting root gate; full tree owning operation recovery |
| S03 | `agent_session/__init__.py:1647` | Complete sorted tree Sessions | Waiting NO KEY UPDATE; no partial subtree |
| S04 | `historical_memory_consolidation/authority.py:259` | Agent | Waiting SHARE under immutable attempt admission bound |
| S05 | `historical_memory_consolidation/authority.py:271` | Personal membership | Waiting SHARE; exact current grant identity |
| S06 | `historical_memory_consolidation/drafts.py:147` | Complete root influence | Pre-unit exact-scope SHARE, including extant denied roots; ordinary post-owner validation |
| S07 | `historical_memory_consolidation/drafts.py:162` | Complete canonical influence | Pre-unit exact-source SHARE; validation restricted to actually locked IDs |
| S08 | `historical_memory_consolidation/lifecycle.py:33` | Canonical source continuity | Waiting UPDATE in the same parent transition; atomic enrollment |
| S09 | `historical_memory_consolidation/cutover.py:110` | Unit page | Waiting UPDATE; actual snapshot-reset check after acquisition |
| S10 | `historical_memory_consolidation/cutover.py:212` | Joined source/root/Agent page | Explicit sorted Agent/membership/root/source acquisition and fresh page identity |
| S11 | `historical_memory_consolidation/cutover.py:252` | Personal membership page | Ordered waiting membership before root/source |
| S12 | `external_account_link/__init__.py:324` | CLAIMED Attempt | Waiting after User/auth; exact context before auth failure settlement |
| S13 | `external_account_link/__init__.py:381` | Active Link | Waiting after Attempt; retain partial uniqueness and reconciliation |
| S14 | `external_account_link/__init__.py:520` | User | Waiting before auth/Attempt/Link |
| S15 | `external_account_link/__init__.py:526` | Auth Session | Waiting after User; current revoke/expiry checked after final wait |
| S16 | `external_account_oauth/repository.py:128` | User | Waiting under Section fence |
| S17 | `external_account_oauth/repository.py:136` | Auth Session | Waiting after User; refreshed expiry/revoke |
| S18 | `external_account_oauth/repository.py:161` | Exact OPEN Attempt | Waiting single-use claim; fresh DB time/context before consumption |
| S19 | `external_channel/model_settings.py:301` | Existing private draft | Waiting reopen with fresh authorization/expiry |
| S20 | `external_channel/model_settings.py:853` | Connection | First routing fence, ordinary wait |
| S21 | `external_channel/model_settings.py:859` | Principal | Ordinary wait after routing/advisory |
| S22 | `external_channel/model_settings.py:865` | Binding | Ordinary wait after Route/Resource |
| S23 | `external_channel/model_settings.py:873` | Resource | Ordinary wait before Binding |
| S24 | `external_channel/model_settings.py:879` | AgentRoute | Ordinary wait after Connection |
| S25 | `external_channel/model_settings.py:895` | Active Link | Ordinary wait after linked User, exact ownership refresh |
| S26 | `external_channel/model_settings.py:903` | Linked User | Ordinary wait before Link |
| S27 | `external_channel/model_settings.py:910` | Root Session | Ordinary wait after Agent |
| S28 | `external_channel/model_settings.py:916` | Agent | Ordinary wait before root Session |
| S29 | `external_channel/model_settings.py:942` | Relevant grants | Stable ordered ordinary wait after authorization advisory |
| S30 | `external_channel/model_settings.py:1425` | Apply draft | Ordinary wait, final current expiry/selection revalidation |
| A01 | `external_channel/repository.py:3768` | Agent/principal authorization key | Same-key `pg_advisory_xact_lock`; remove try mode/boolean/synthetic conflict |

**Retained nonwaiting exceptions: none.** Underlying exclusion remains effective;
queue `SKIP LOCKED` and asynchronous queue APIs are not removal targets.

## Closed Recovery and Writer Evidence

- The finite hierarchy closure has 25 owning entries: four Subagent mutations,
  seven tree transitions, twelve owned terminal operations and two standalone
  repairs. Composing helpers never replay caller-held writes. Real PostgreSQL
  deadlocks cover both possible victims, including public Stop versus terminal
  finalization. Original owner/Run/task inputs remain unchanged.
- Memory has twelve complete-influence owners and three new-exposure owners.
  Complete body-free UUID plans are uncapped; current authority and full version
  validation remain server-side. Extant denied identities are locked before the
  unit, so restore cannot introduce an unprotected participant after validation.
  No new root/source lock is acquired by the post-unit manifest validator.
- Pre-unit waiting uses the original attempt cutoff; after exact owner acquisition,
  the current renewable lease narrows acceptance. Actual heartbeat extension,
  cancellation, deadline loss, changed plan and recovery invalidation are tested.
- Stage 1 uses Agent -> membership -> root -> source acquisition. The Agent
  memory-toggle gate is FK-compatible NO KEY UPDATE, eliminating the concrete
  toggle/source versus archive/enrollment-FK cycle without a new coordinator.
- OAuth exchange and model/notice delivery remain outside recovery. Exact
  CLAIMED context precedes authorization failure settlement, preventing failure
  mutation of a mismatched Attempt. Existing model 250ms/three-attempt and
  finalization three-attempt policies remain unchanged.
- Offline recovery restarts only a fully rolled-back page from its original
  committed cursor. Actual false quiescence/reset predicates remain failures;
  contention alone is not proof of a false operator precondition.

## Verification Evidence

Credential-free isolated PostgreSQL tests use actual blocking observations and
explicit barriers, not scheduler sleeps. Local focused/integrated evidence:

- Hierarchy/terminal integration: 238 passed, including both actual deadlock victims.
- Public Stop/terminal ownership file: 12 passed after replacing its obsolete
  LockNotAvailable hook with actual owning-operation contention.
- Historical Memory repository/service and policy integration: 319 passed,
  including 10,100/20,000 UUID plans, captured model output, heartbeat, restore,
  complete manifests, offline pages and unchanged foreground read independence.
- External account/model integration: 156 passed, including every guard/advisory,
  one exchange, mismatched context, elapsed auth expiry and opposing real writers.
- Stage 1/source integration: 54 passed.
- Helper/policy checks: 11 passed; baseline 30 row/one advisory acquisitions reach
  zero, and the finite hierarchy decorator closure is checked exactly.
- Documentation catalog tests: 18 passed; catalog validation passes.
- Final whole-backend pytest: 10,982 passed, three pre-existing skips, 121
  warnings, 439.80 seconds. Full backend Ruff, formatting and type checking pass.
- Independent production reviews, targeted security corrections and Spec review:
  clear. Six Living Specs reflect the implemented timing/recovery contracts.

These overlapping suites are reported separately, not summed. Final-SHA required
CI is recorded in the PR delivery report. Required
failures are corrected rather than skipped; optional paid/live provider workflows
are not invoked. No production settings/data, generated clients, migration,
merge or deployment is part of this work.
