---
title: "Discord Slack Parity Integrated Delivery Execution Plan"
created: 2026-07-28
tags: [discord, slack, external-channel, backend, frontend, testenv]
---

# Discord Slack Parity Integrated Delivery Execution Plan

## Scope

This is the mandatory execution plan for the one-PR implementation of
`discord-260728`. It implements all design vertical slices together while retaining
explicit completion gates for each surface.

## Preconditions checked

- Same-basename Requirements, ADR, and Design exist for `discord-260728`.
- Slack remains the semantic source of truth; provider-specific behavior is confined to
  Discord ingress and presentation adapters.
- Current External Channel specs and deterministic Discord E2E policy have been read.
- No database migration is planned unless an existing validated persisted shape cannot
  safely distinguish source, root, existing thread, and delivery identities.

## Ordered changes

1. **Ingress and selector**
   - Parse safe Discord Message Command/component/modal facts.
   - Claim durable interactions before constructing request-local Discord responses.
   - Materialize selected source messages through the shared source boundary.
   - Reuse selector authorization, signed scope, navigation, and immutable selection.

2. **Conversation activation and delivery**
   - Normalize root/existing-thread resource labels and ensure one delivery thread.
   - Route access controls, Session links, checking progress, replies, and files to that
     target.
   - Dispatch bounded Discord hydration through the existing resource barrier.
   - Remove provider-specific early exits that skip canonical release, work, or mailbox
     wake behavior.
   - Reuse page projection state for recovery and lifecycle cleanup.

3. **Management and UI**
   - Add provider-correct Discord Multi operations to the public management route.
   - Regenerate OpenAPI clients after route changes.
   - Generalize tRPC and Workspace Slack Apps presentation without reducing Slack
     behavior.

4. **Verification and documentation**
   - Add focused regression coverage for every changed adapter/orchestration boundary.
   - Add deterministic participant/admin and browser E2E coverage.
   - Reconcile affected living specs, run docs index validation, review the final diff,
     and remediate PR CI until green.

## Exclusions

- No Slack behavior change except a provider-neutral extraction required to give Discord
  the identical canonical lifecycle.
- No transient Discord token/signature/raw-payload persistence or replay.
- No merge, deployment, force push, destructive reset, or production mutation.

## Acceptance gate

The PR is complete only when each `discord-260728/REQ-*` acceptance criterion has a
mapped implementation and deterministic evidence, generated artifacts match their
source, the relevant living specs describe the resulting behavior, and required PR CI
is green.
