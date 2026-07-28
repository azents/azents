---
title: "Discord Slack Parity Completion Checklist"
created: 2026-07-28
tags: [discord, slack, external-channel, parity, implementation, validation]
---

# Discord Slack Parity Completion Checklist

## Source of Truth

- Requirements: `docs/azents/requirements/discord-260728-slack-parity.md`
- ADR: `docs/azents/adr/discord-260728-slack-parity.md`
- Design: `docs/azents/design/discord-260728-slack-parity.md`
- Current implementation plan:
  `docs/azents/plans/discord-260728-slack-parity-implementation-plan.md`
- Completion status values: `Pending`, `In progress`, `Completed`, `Blocked`

This checklist is the execution ledger for closing every remaining Discord-to-Slack
External Channel parity gap. An item is `Completed` only when its implementation,
focused tests, required E2E evidence, documentation impact, and PR CI are complete.

## Completion Summary

| Area | Status | Evidence |
| --- | --- | --- |
| Delivery diagnostics and provider operation correctness | Pending | |
| Activation, hydration, and pre-execution ordering | Pending | |
| Invocation and selected-message entry points | Pending | |
| Multi App selector and access flow | Pending | |
| Thread-scoped delivery | Pending | |
| Session, Channel Work, replies, files, and recovery | Pending | |
| Multi App administration and Workspace UI | Pending | |
| Lifecycle, security, and operational behavior | Pending | |
| Deterministic participant E2E | Pending | |
| Deterministic administration and browser E2E | Pending | |
| Living-spec reconciliation | Pending | |
| Stacked PR review and CI | In progress | Plan branch prepared from `origin/main` |

## A. Delivery Diagnostics and Provider Correctness

- [ ] `A-01` Reproduce the production `provider_ambiguous` outcome through a
      deterministic Discord provider scenario.
- [ ] `A-02` Distinguish safe unknown-result categories for transport failure,
      provider 5xx, malformed JSON, invalid response shape, channel mismatch, and
      invalid thread response without retaining provider bodies.
- [ ] `A-03` Preserve at-most-once behavior for ambiguous Discord writes.
- [ ] `A-04` Preserve deterministic Discord create-message nonces.
- [ ] `A-05` Add structured, Discord-specific safe logging for provider operation,
      status category, and durable delivery identity.
- [ ] `A-06` Ensure logs never contain Bot credentials, signatures, interaction
      tokens, selectors, raw bodies, attachment URLs or bytes, message contents, or
      exception text.
- [ ] `A-07` Verify Discord REST requests use the configured production/test API base
      consistently for GET, POST, PATCH, DELETE, thread, and file operations.
- [ ] `A-08` Add focused tests for every safe Discord delivery result category.
- [ ] `A-09` Add deterministic fixture evidence for each controlled Discord delivery
      failure boundary.
- [ ] `A-10` Confirm the production failure's sanitized root-cause category after the
      corrected diagnostics are deployed; do not retry ambiguous historical writes.

## B. Activation, Hydration, and Pre-Execution Ordering

- [ ] `B-01` Start every new Discord binding in `waiting_hydration`.
- [ ] `B-02` Remove the Discord immediate-`ACTIVE` binding exception.
- [ ] `B-03` Prevent initial invocation batch creation before Discord hydration is
      terminal.
- [ ] `B-04` Prevent initial mailbox creation before the reconciliation boundary is
      clear.
- [ ] `B-05` Prevent initial Session wake before Discord hydration and correlated-event
      reconciliation complete.
- [ ] `B-06` Hydrate a root-message source before initial activation.
- [ ] `B-07` Hydrate an existing Discord thread before initial activation.
- [ ] `B-08` Reconcile out-of-order Gateway events with fetched history.
- [ ] `B-09` Preserve bounded cursor, high-watermark, and reconciliation-boundary
      semantics.
- [ ] `B-10` Handle history rate limits with bounded deferred retry.
- [ ] `B-11` Handle history temporary failure without activating incomplete context as
      successful.
- [ ] `B-12` Handle history permission and credential failures through the existing
      reconnect-required fence.
- [ ] `B-13` Handle unavailable history resources through the provider-loss lifecycle.
- [ ] `B-14` Release retained context exactly once after every activation fence passes.
- [ ] `B-15` Create the initial invocation batch and mailbox item idempotently.
- [ ] `B-16` Create initial Session-link and checking-progress delivery intents in the
      same activation transaction.
- [ ] `B-17` Attempt required initial provider setup before Session wake.
- [ ] `B-18` Define and implement the initial-delivery success/failed/unknown execution
      gate consistent with Slack-visible behavior and at-most-once delivery.
- [ ] `B-19` Mark the binding active only after the fenced activation sequence.
- [ ] `B-20` Add ordering tests that assert hydration, initial provider setup, and wake
      transitions rather than only asserting intent creation.
- [ ] `B-21` Make Discord approval Allow create a `waiting_hydration` binding without
      immediate pending-context release or wake.
- [ ] `B-22` Make selected-admission continuation dispatch by provider instead of using
      Slack labels, payloads, and defaults.
- [ ] `B-23` Consume initial Session-link, progress, and approval-control intents through
      one provider-dispatched delivery boundary.

## C. Invocation and Selected-Message Entry Points (`REQ-1`)

- [ ] `C-01` Verify eligible Discord mentions retain source text, supported
      attachments, and bounded context before execution.
- [ ] `C-02` Verify the registered Guild Message Command retains the selected source
      without requiring copied or rewritten text.
- [ ] `C-03` Verify Message Command source projection preserves root and existing-thread
      identities.
- [ ] `C-04` Verify selected-message source materialization commits before selector
      processing.
- [ ] `C-05` Verify existing bound conversations preserve immutable Agent selection.
- [ ] `C-06` Verify duplicate Gateway delivery creates no second resource, binding,
      invocation batch, mailbox item, or wake.
- [ ] `C-07` Verify duplicate Message Command delivery creates no second durable
      execution effect.
- [ ] `C-08` Verify delayed and repeated provider deliveries converge on the same
      canonical message revision and binding.
- [ ] `C-09` Add deterministic E2E for mention entry.
- [ ] `C-10` Add deterministic E2E for selected-message entry.

## D. Multi App Selector and Access Flow (`REQ-2`)

- [ ] `D-01` List only active Agents associated with the selected Discord Multi App.
- [ ] `D-02` Present immediate-access and approval-required route states distinctly.
- [ ] `D-03` Preserve complete route-catalog pagination without silent truncation.
- [ ] `D-04` Preserve route search across the complete catalog.
- [ ] `D-05` Bind selector component scope to connection, resource, admission,
      principal, and page state.
- [ ] `D-06` Recheck connection health, app mode, route catalog, admission expiry,
      actor identity, and Workspace scope on every selector interaction.
- [ ] `D-07` Reject unsigned, tampered, cross-Guild, cross-connection, cross-resource,
      and wrong-actor selection.
- [ ] `D-08` Allow one pending conversation to select a route at most once.
- [ ] `D-09` Route approval-required selection through the existing approval flow.
- [ ] `D-10` Route immediate-access selection through hydration-fenced activation.
- [ ] `D-11` Preserve source-message principal provenance rather than replacing it with
      the interaction actor.
- [ ] `D-12` Add deterministic E2E for selector initial page, next/previous navigation,
      route selection, and duplicate submission.

## E. Deterministic Thread Boundary (`REQ-3`)

- [ ] `E-01` Create or reuse the root source message's Discord thread only after route
      resolution.
- [ ] `E-02` Reuse an invocation's existing Discord thread without creating a second
      thread.
- [ ] `E-03` Persist source channel, parent channel, root message, existing thread, and
      delivery channel identities distinctly.
- [ ] `E-04` Make thread provisioning concurrency-safe and idempotent.
- [ ] `E-05` Converge concurrent or retried provisioning on one canonical thread.
- [ ] `E-06` Route approval controls into the canonical conversation thread.
- [ ] `E-07` Route Session links into the canonical conversation thread.
- [ ] `E-08` Route checking/progress pages into the canonical conversation thread.
- [ ] `E-09` Route replies and files into the canonical conversation thread.
- [ ] `E-10` Route progress cleanup and approval-control cleanup into the canonical
      conversation thread.
- [ ] `E-11` Prevent root-channel approval or Session controls from being posted
      outside their conversation.
- [ ] `E-12` Add deterministic E2E proving one shared thread for all provider-visible
      output.
- [ ] `E-13` Correct root-message approval control targeting so thread provisioning
      metadata is present before the control is delivered.

## F. Authorization and Context Release (`REQ-4`)

- [ ] `F-01` Preserve provider-neutral grants, session grants, blocks, denials, expiry,
      and revocation semantics.
- [ ] `F-02` Ensure block takes precedence over automatic access and grants.
- [ ] `F-03` Ensure denied and blocked requests never release new input.
- [ ] `F-04` Ensure allow releases retained input exactly once after commit.
- [ ] `F-05` Ensure repeated compatible allow decisions reuse the same binding, batch,
      mailbox item, and Session.
- [ ] `F-06` Ensure conflicting or stale decisions cannot create parallel state.
- [ ] `F-07` Delete delivered approval controls only through durable provider-aware
      delivery intents.
- [ ] `F-08` Preserve failed or ambiguous approval-control deletion as durable evidence.
- [ ] `F-09` Add deterministic E2E for `allow_session`, `allow_agent`, `deny`, and
      `block`.
- [ ] `F-10` Add deterministic E2E for revocation and subsequent invocation behavior.

## G. Session, Channel Work, Replies, Files, and Recovery (`REQ-5`)

- [ ] `G-01` Create exactly one initial Session-link delivery for a new binding.
- [ ] `G-02` Create exactly one initial checking progress projection.
- [ ] `G-03` Ensure both initial projections are provider-visible before execution
      according to the initial-delivery gate.
- [ ] `G-04` Create Discord progress pages in stable ordinal order.
- [ ] `G-05` Update only changed Discord progress pages.
- [ ] `G-06` Create new pages in order and delete surplus pages in order.
- [ ] `G-07` Preserve durable provider message identities per projection part.
- [ ] `G-08` Deliver continuations in the canonical thread.
- [ ] `G-09` Deliver final replies in the canonical thread.
- [ ] `G-10` Split bounded Discord reply pages deterministically.
- [ ] `G-11` Deliver Runtime files through current authority and streaming validation.
- [ ] `G-12` Deliver Exchange files through current authority and revalidation.
- [ ] `G-13` Preserve Agent identity presentation for text and file messages.
- [ ] `G-14` Gate progress cleanup on successfully delivered final reply parts.
- [ ] `G-15` Do not report cleanup success after failed or ambiguous final delivery.
- [ ] `G-16` Recover a confirmed deleted or missing active progress page.
- [ ] `G-17` Do not blindly replay an ambiguous progress mutation.
- [ ] `G-18` Add deterministic E2E for progress create, update, page growth, page
      reduction, final reply, and cleanup.
- [ ] `G-19` Add deterministic E2E for progress deletion recovery.
- [ ] `G-20` Add deterministic E2E for Runtime and Exchange file output.
- [ ] `G-21` Connect Discord inbound message-deletion events to active progress-page
      recovery.
- [ ] `G-22` Derive Discord projection drift from authoritative projection parts rather
      than the Slack legacy progress key.

## H. Discord Multi App Administration (`REQ-6`)

- [ ] `H-01` Verify list and get Discord Multi App operations.
- [ ] `H-02` Verify setup, validation, update, impact preview, and disconnect.
- [ ] `H-03` Verify route list, add, remove, re-enable, impact, and immutable route
      binding behavior.
- [ ] `H-04` Verify channel-default list, replace, and clear.
- [ ] `H-05` Verify destructive operation permission checks and generation fences.
- [ ] `H-06` Verify provider-correct public API operation names.
- [ ] `H-07` Regenerate and verify OpenAPI, Python client, and TypeScript client.
- [ ] `H-08` Verify provider-aware tRPC dispatch.
- [ ] `H-09` Verify Workspace UI lists Slack and Discord without hiding Slack
      functionality.
- [ ] `H-10` Verify Discord setup, edit, validation, routes, defaults, impact, and
      disconnect UI.
- [ ] `H-11` Verify Workspace UI never exposes credentials or raw provider failure
      details.
- [ ] `H-12` Add deterministic public API E2E for every Discord Multi management
      operation.
- [ ] `H-13` Add browser E2E for Discord Workspace management and destructive fences.
- [ ] `H-14` Provide a provider-correct Workspace integrations route, navigation label,
      page, component, container, and translation namespace.
- [ ] `H-15` Restore the provider when opening a direct Discord connection deep link.
- [ ] `H-16` Replace the shared-offset dual-provider list with stable combined
      pagination behavior.
- [ ] `H-17` Add meaningful Discord setup, edit, validation, error, impact,
      disconnected, and generation-fence stories or component tests.

## I. Lifecycle, Security, and Operations (`REQ-7`)

- [ ] `I-01` Validate required Discord capabilities during activation.
- [ ] `I-02` Preserve transient-only interaction tokens, signatures, raw requests, and
      selector values.
- [ ] `I-03` Preserve redacted attachment URL and byte boundaries.
- [ ] `I-04` Preserve Gateway lease, checkpoint, session, configuration-generation,
      and app-claim fences.
- [ ] `I-05` Preserve reconnect behavior for recoverable Gateway failures.
- [ ] `I-06` Terminalize credential and non-reconnectable Gateway failures correctly.
- [ ] `I-07` Preserve route, binding, and work state during provider health failure.
- [ ] `I-08` Disconnect bindings and connections through terminal canonical state
      before provider cleanup.
- [ ] `I-09` Archive Session bindings and create Discord progress cleanup intents.
- [ ] `I-10` Decommission Agents through normal External Channel lifecycle cleanup.
- [ ] `I-11` Keep failed or ambiguous cleanup visible without canonical rollback.
- [ ] `I-12` Verify Discord-specific safe operator labels for ingress, normalization,
      hydration, delivery, and Gateway failures.
- [ ] `I-13` Correct any Slack-labelled Discord logs.
- [ ] `I-14` Add deterministic E2E for disconnect, credential failure,
      reconnect-required, archive cleanup, and Agent decommission.

## J. Deterministic Evidence (`REQ-8`)

- [ ] `J-01` Extend the Discord fake with Message Command source payload support.
- [ ] `J-02` Extend the Discord fake with selector component and response evidence.
- [ ] `J-03` Extend the Discord fake with bounded root/thread history pages.
- [ ] `J-04` Extend the Discord fake with deterministic thread create/reuse evidence.
- [ ] `J-05` Extend the Discord fake with create/update/delete/file evidence.
- [ ] `J-06` Extend the Discord fake with controlled response-shape and transport
      failures.
- [ ] `J-07` Add full participant E2E: mention or Message Command → selector → approval
      → allow → hydration → Session link/progress → one wake → reply/file → cleanup.
- [ ] `J-08` Add authorized continuation E2E in the same thread.
- [ ] `J-09` Add deleted-progress recovery E2E.
- [ ] `J-10` Add Discord Multi public API E2E.
- [ ] `J-11` Add Discord Workspace browser management E2E.
- [ ] `J-12` Add lifecycle and reconnect E2E.
- [ ] `J-13` Assert test evidence excludes credentials, tokens, signatures, selectors,
      raw provider payloads, attachment URLs, file bytes, and message contents.
- [ ] `J-14` Run the complete deterministic E2E lane.
- [ ] `J-15` Run the complete web-surface E2E lane.

## K. Living Specs and Documentation

- [ ] `K-01` Compare implementation against
      `docs/azents/spec/domain/external-channel.md`.
- [ ] `K-02` Compare implementation against
      `docs/azents/spec/flow/external-channel-provider-ingress.md`.
- [ ] `K-03` Compare implementation against
      `docs/azents/spec/flow/external-channel-authorization.md`.
- [ ] `K-04` Compare implementation against
      `docs/azents/spec/flow/external-channel-delivery.md`.
- [ ] `K-05` Compare implementation against
      `docs/azents/spec/flow/external-channel-lifecycle.md`.
- [ ] `K-06` Compare implementation against
      `docs/azents/spec/flow/test-strategy-e2e-primary.md`.
- [ ] `K-07` Remove the current false claim that Discord begins activation after
      hydration only when code and evidence do not support it.
- [ ] `K-08` Promote the corrected hydration-fenced behavior only after implementation
      and deterministic evidence pass.
- [ ] `K-09` Update living-spec verification dates and versions only after matching
      implementation and E2E evidence.
- [ ] `K-10` Preserve the accepted ADR unchanged.
- [ ] `K-11` Mark Requirements and Design implemented only after every mandatory item
      in this checklist is complete.
- [ ] `K-12` Run spec review and documentation index validation.

## L. Quality, Review, PR, CI, and Rollout

- [ ] `L-01` Create and maintain the multi-phase implementation plan.
- [ ] `L-02` Create one mandatory execution plan before each implementation phase.
- [ ] `L-03` Run focused Ruff and format checks for changed Python paths.
- [ ] `L-04` Run focused Pyright and Python tests for changed backend paths.
- [ ] `L-05` Run TypeScript format, lint, typecheck, and build checks.
- [ ] `L-06` Run generated-client contract tests.
- [ ] `L-07` Run Discord provider fake contract tests.
- [ ] `L-08` Run complete relevant backend External Channel tests.
- [ ] `L-09` Run complete deterministic E2E.
- [ ] `L-10` Run complete web-surface E2E.
- [ ] `L-11` Perform independent code review for each implementation phase.
- [ ] `L-12` Remediate requirements, security, data-loss, and material interface
      findings.
- [ ] `L-13` Create every planned stacked PR before waiting on CI.
- [ ] `L-14` Request `hardtack` as reviewer on every PR.
- [ ] `L-15` Monitor all stacked PR checks until green.
- [ ] `L-16` Fix every relevant CI failure without bypassing hooks or force-pushing
      unreviewed work.
- [ ] `L-17` Obtain explicit approval before merging any PR.
- [ ] `L-18` Monitor deployment only after merge and explicit deployment scope.
- [ ] `L-19` Validate a new Discord root conversation after corrected deployment.
- [ ] `L-20` Confirm provider-visible thread, Session link, progress, reply, file, and
      cleanup behavior in the new conversation.
- [ ] `L-21` Remove stale implementation and phase plans in the final cleanup PR.

## Findings Ledger

| ID | Status | Finding | Resolution PR | Validation |
| --- | --- | --- | --- | --- |
| `FIND-01` | In progress | Initial Discord delivery attempts can fail or become unknown while Session wake still proceeds. | | |
| `FIND-02` | In progress | New Discord bindings are marked active and released before hydration, contrary to Requirements and living specs. | | |
| `FIND-03` | In progress | Production control, progress, and reply delivery returned `provider_ambiguous` without a useful safe category. | | |
| `FIND-04` | In progress | Participant E2E stops at interaction/Gateway admission and does not prove the complete Discord conversation journey. | | |
| `FIND-05` | In progress | Discord Workspace management has API E2E but no browser E2E. | | |
| `FIND-06` | In progress | Progress recovery, lifecycle cleanup, replies, and files have focused tests but no integrated Discord E2E. | | |
| `FIND-07` | In progress | Living specs claim hydration-fenced Discord activation that current code does not implement. | | |
| `FIND-08` | In progress | Discord selected-admission continuation and Allow paths retain Slack defaults or immediate release behavior. | | |
| `FIND-09` | In progress | Root-message approval controls can target the parent channel because thread metadata is not added correctly. | | |
| `FIND-10` | In progress | Lifecycle cleanup ignores authoritative Discord progress projection parts and can orphan provider pages. | | |
| `FIND-11` | In progress | Confirmed missing Discord progress pages and inbound message deletes do not recreate active desired pages. | | |
| `FIND-12` | In progress | Direct Discord Workspace connection deep links do not restore the selected provider. | | |
| `FIND-13` | In progress | Shared-offset Slack/Discord list queries do not provide stable combined pagination. | | |
| `FIND-14` | In progress | Concurrent initial deliveries can race root-thread provisioning because the provider mutation is not claimed under a canonical resource fence. | | |

## PR Stack Ledger

| Order | Branch | PR | Scope | Status |
| --- | --- | --- | --- | --- |
| 1 | `fix/discord-slack-parity-completion` | | Implementation plan and checklist | In progress |
| 2 | | | Delivery diagnostics and activation ordering | Pending |
| 3 | | | Participant, work, and lifecycle completion | Pending |
| 4 | | | Administration UI and browser evidence | Pending |
| 5 | | | Integrated E2E validation and fixes | Pending |
| 6 | | | Living-spec promotion | Pending |
| 7 | | | Plan cleanup | Pending |
