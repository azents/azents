---
title: "Immediate External Channel Provider Delivery"
created: 2026-08-02
tags: [external-channel, slack, discord, architecture]
document_role: primary
document_type: adr
snapshot_id: channel-260802
---

# Immediate External Channel Provider Delivery

- Snapshot: `channel-260802`
- Requirements: [`channel-260802/REQ`](../requirements/channel-260802-immediate-provider-delivery.md)

## Context

External Channel publication currently commits a durable Channel Action and one or
more durable delivery attempts before calling Slack or Discord. Those records own
special duplicate-call recovery, provider-attempt state, rendered payloads, Runtime
transfer settlement, current and historical provider outcomes, and management
delivery history.

The confirmed Requirements replace that workflow with ordinary synchronous Tool
execution. Session history remains the sole durable Agent-requested execution
history. Non-Tool provider controls become direct post-commit best-effort effects,
and the existing Action and delivery-attempt records are deleted without a
replacement queue, ledger, or compatibility path.

The remaining External Channel domain still owns current binding, resource,
connection, authorization, Channel Work, and provider projection state. The design
must separate that current state from the removed execution history.

## Fixed or Derived Outcomes

The following outcomes are already determined and are not decision points:

- Canonical Channel Work changes commit before provider I/O and are not rolled back
  or compensated when the provider fails (`channel-260802/REQ-1`,
  `channel-260802/REQ-4`).
- Every provider effect runs directly in the current Tool or post-commit control
  path. There is no pending state, Worker drain, startup recovery, replay, or
  External-Channel-specific cancellation recovery (`channel-260802/REQ-1`,
  `channel-260802/REQ-3`, `channel-260802/REQ-5`).
- Multiple foreground Tool calls retain the normal engine execution policy,
  including parallel execution. External Channel does not add a separate scheduler
  or durable per-binding execution queue (`channel-260802/REQ-1`).
- Direct provider effects may partially succeed. A later failure does not compensate
  an earlier provider mutation or a committed domain transition
  (`channel-260802/REQ-1`, `channel-260802/REQ-4`,
  `channel-260802/REQ-5`).
- Runtime and Exchange authorization remains at the live provider boundary. An
  interrupted Runtime claim follows its existing bounded expiration or cleanup
  lifecycle and never causes provider replay (`channel-260802/REQ-6`).
- Terminal lifecycle paths capture any credential-bearing provider target in memory
  before credential purge, commit canonical terminal state first, and then attempt
  cleanup directly. They do not persist the captured target
  (`channel-260802/REQ-3`, `channel-260802/REQ-4`).
- Current provider message identities required for later progress update or cleanup
  remain domain state. Historical attempts and outcomes do not
  (`channel-260802/REQ-4`).
- Management removes the delivery-history list and generated contract. It may expose
  current Channel Work projection state, but not a replacement operation history
  (`channel-260802/REQ-2`, `channel-260802/REQ-4`,
  `channel-260802/REQ-7`).
- One new destructive migration removes both legacy tables, their foreign keys,
  indexes, and delivery-only enums. The rollout has no dual-read, dual-write,
  fallback, archive, export, or backfill mode (`channel-260802/REQ-2`,
  `channel-260802/REQ-7`).

## Decision Backlog

| Order | Decision point | Dependency | Status |
| --- | --- | --- | --- |
| DP1 | Immediate `channel_action` Tool-result semantics | None | Accepted as ADR-D1 |
| DP2 | Ownership of current provider projection state after delivery-history removal | DP1 | Accepted as ADR-D2 |

This backlog contains every unresolved choice that changes the product contract,
durable source of truth, or failure behavior. If repository analysis reveals another
material choice, the complete backlog must be re-briefed before that choice is made.

## Agent-Owned Implementation Categories

After the material decisions are accepted, the Design may choose local reversible
details without additional requester decisions:

- class, function, field, and migration revision names;
- service and repository helper boundaries;
- ephemeral in-memory provider plan and outcome types;
- equivalent owner-local column placement authorized by the accepted projection
  ownership decision;
- safe log event names, metric names, and test fixture composition;
- test file placement and generated-client regeneration mechanics.

These details may not introduce another history, queue, retry mode, compatibility
path, or source of truth.

## Decisions

### `channel-260802/ADR-D1` — Return ordered per-effect outcomes through the ordinary Tool result

**Affects:** `channel-260802/REQ-1`, `channel-260802/REQ-2`,
`channel-260802/REQ-5`, `channel-260802/REQ-6`

A valid `channel_action` invocation returns one structured ordinary Tool result
containing the current binding and Channel Work state plus the ordered immediate
outcome of each provider effect executed by that invocation. Each effect identifies
its semantic operation and reports `delivered`, `failed`, `unknown`, or
`not_attempted` as applicable.

The result may represent partial success. A successful reply followed by a failed
progress cleanup remains an explicit successful reply and failed cleanup rather than
being collapsed into one aggregate status. A planned effect may be
`not_attempted` when an earlier required effect prevents it from being invoked.

The result contains no Channel Action identifier, delivery-attempt identifier,
provider message identifier, stored request payload, or recovery metadata. It is
durable only because the normal Session history records the Tool call and result.

Input-schema failures, invalid domain transitions, failed authorization, unavailable
file sources, and other failures detected before provider mutation use the normal
Tool error path. Once provider mutation begins, confirmed rejection and ambiguity
are represented by the structured `failed` or `unknown` effect outcome so the model
can distinguish them from pre-provider validation and can observe partial success.

Rejected alternatives:

- One aggregate outcome was rejected because it would discard partial success and
  conceal which requested provider effect failed or became ambiguous.
- Converting every failed or unknown provider effect into a framework Tool error was
  rejected because it would obscure completed mutations and make an ambiguous
  provider result indistinguishable from a pre-provider Tool failure.

### `channel-260802/ADR-D2` — Keep minimal current provider projection state on its domain owner

**Affects:** `channel-260802/REQ-2`, `channel-260802/REQ-3`,
`channel-260802/REQ-4`, `channel-260802/REQ-5`,
`channel-260802/REQ-7`

Each canonical domain object owns only the current provider projection state required
for its next valid operation. There is no generic provider-projection registry and no
replacement delivery ledger.

Channel Work owns the current progress projection identity, desired revision,
current projection status, and ordered part identity where the provider requires
multiple retained messages. That state supports later update, delete, replacement,
current-state management display, and ambiguity fencing without retaining the
provider operations that produced it.

An access request, setup claim, interaction, binding, or other control owner may
retain a current provider message identity only when its existing lifecycle requires
a later direct update or deletion. The identity belongs to that object and is
cleared or terminalized with the owning lifecycle. Controls that have no later
mutation retain no provider result state.

Direct provider completion updates current projection state only while the expected
owner identity and revision remain current. A stale completion cannot overwrite a
newer canonical projection. The current state may record `failed` or `unknown` when
that status is required to avoid an unsafe later mutation or to preserve the current
management projection, but it does not retain request payloads, attempt identifiers,
timestamps, error history, or a sequence of outcomes.

Exact owner-local fields and whether equivalent Channel Work state is represented on
the Work row or its existing ordered projection-part rows are Design-owned details.
They must preserve one owner and may not recreate a cross-domain operation ledger.

Rejected alternatives:

- A generic current-provider-projection table was rejected because it would create a
  second cross-domain authority that could grow back into the removed delivery
  workflow.
- Retaining only provider message identifiers without current revision or ambiguity
  state was rejected because stale completions could overwrite newer progress state,
  unknown mutations could be repeated unsafely, and the existing current projection
  display could not be preserved.
