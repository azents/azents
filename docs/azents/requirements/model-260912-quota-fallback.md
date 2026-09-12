---
title: "Model Quota Fallback Requirements"
created: 2026-09-12
updated: 2026-09-12
tags: [models, agent, reliability, frontend]
document_role: primary
document_type: requirements
snapshot_id: model-260912
---

# Model Quota Fallback Requirements

- Snapshot: `model-260912`
- Document reference: `model-260912/REQ`

## Problem

An Agent operation stops when its selected physical model exhausts an account, plan, credit, or billing quota even when another configured model could perform the same requested work. The user must currently change model selection and retry manually, while repeated attempts may continue targeting the exhausted model.

## Primary Context

### Primary Actor

A Workspace member running an Agent through a Session or another supported Agent input boundary.

### Primary Scenario

The member starts work using an Agent-owned semantic model label. The selected physical model returns a classified quota or billing failure. Azents preserves the requested label and explicit execution intent, continues the same logical operation through the label's configured fallback candidates, and either completes through a compatible candidate or presents one terminal recovery state after the chain is exhausted.

## Supporting Scenarios or Effects

- Workspace managers configure the same label-local chain defaults that new Agents copy at creation time.
- Automatic context compaction and Session title generation use the Agent's Lightweight label chain
  without changing foreground Session label intent or Primary reservation. A physical quota observed
  in background work remains part of Workspace-shared candidate availability.
- A user who restores quota can reserve one real foreground request to retry the selected label's Primary candidate.
- Worker handover, restart, reconnect, and manual failed-run retry preserve the defined execution boundary rather than repeating already exhausted candidates silently.

## Goals

- Continue eligible Agent work automatically after a confirmed quota or billing failure.
- Preserve semantic model intent, explicit reasoning effort, and execution options during fallback.
- Provide bounded, understandable configuration and low-noise recovery controls on desktop and mobile.
- Prevent repeated quota calls to the same candidate within one logical operation.
- Share short-lived candidate unavailability across the Workspace without relying on provider reset estimates.

## Non-Goals

- Automatic fallback between different semantic model labels.
- Predictive routing from subscription usage percentages or provider reset timestamps.
- Applying this fallback policy to ordinary rate limits.
- Silently lowering reasoning effort, disabling execution options, or otherwise weakening the accepted request.
- Exponential cooldown escalation or synthetic provider health-check requests.
- Adding fallback status or internal candidate order to every Agent response.

## Requirements

### REQ-1. Label-local ordered candidate configuration

Each Agent-owned selectable model label supports an ordered chain of one to five physical model candidates. The first saved candidate is Primary and later candidates are ordered fallbacks.

**Acceptance criteria**

- A label always retains at least one candidate and rejects a sixth candidate.
- Candidates can be added, replaced, reordered, removed, and saved as one pending settings change.
- Reordering changes which candidate is Primary for future operations.
- The same integration and model pair cannot appear twice in one label, while separate labels may use the same pair.
- Each candidate retains independent model selection, context/output limits, and built-in-tool settings.
- A one-time Primary-settings copy copies only compatible values and creates no continuing inheritance.
- Desktop and mobile settings expose role, model/connection, and actions without an always-visible capability matrix.

### REQ-2. Request-compatible fallback

Fallback preserves the selected semantic label and every explicit request capability.

**Acceptance criteria**

- Fallback does not change the Session's applied label.
- Explicit reasoning effort and execution options remain unchanged.
- A candidate that cannot satisfy the explicit request is skipped without changing the request.
- If no configured candidate can satisfy the request, the operation reaches one explainable terminal state.

### REQ-3. Quota-triggered candidate progression

A classified quota or billing failure advances the current logical operation to the next eligible candidate immediately.

**Acceptance criteria**

- Only normalized `quota_or_billing` provider failures trigger this progression.
- Ordinary `rate_limit` failures retain their existing behavior.
- A candidate that returns `quota_or_billing` is called at most once in the same logical operation.
- Quota progression does not consume repeated same-candidate retry attempts before advancing.
- Main sampling uses the selected Default label chain.
- Automatic compaction and title generation use the selected Lightweight label chain.
- Exhausting every eligible candidate produces a terminal failure instead of restarting the chain.
- Other failure categories retain their existing classified behavior.

### REQ-4. Workspace-shared candidate cooldown

A confirmed quota or billing failure temporarily marks the physical candidate unavailable across the Workspace.

**Acceptance criteria**

- Candidate identity is the Workspace-scoped integration and model pair.
- The cooldown lasts five minutes and does not use provider reset timestamps or usage percentages.
- Removing a candidate from one Agent does not end an active cooldown for the same identity.
- Expiry permits one concurrent half-open real request; other concurrent operations continue to later eligible candidates.
- A successful probe clears cooldown and a quota failure starts a new five-minute cooldown.
- The feature remains correct when Redis is unavailable or restored empty.

### REQ-5. Durable operation boundaries and recovery

One logical operation uses a stable candidate-chain view and does not forget candidate progression across supported recovery boundaries.

**Acceptance criteria**

- A fresh operation resolves the current Agent configuration.
- An in-flight operation retains its prepared chain even if Agent settings change.
- Worker handover or restart preserves the current candidate position and already attempted quota candidates.
- User Stop ends the active Run without starting fallback replay.
- Manual failed-run retry starts a new Run and resolves a fresh current chain.
- Background compaction or title fallback does not change the foreground Session's selected label or
  Primary reservation. A Workspace-shared cooldown observed in background work remains visible on a
  later authoritative availability read.

### REQ-6. Low-noise status and Primary recovery control

Users can understand current fallback availability and deliberately retry Primary without adding routing metadata to normal responses.

**Acceptance criteria**

- Normal availability shows no fallback badge or cooldown panel.
- When the selected label's Primary is unavailable, the Composer model control shows a compact `Fallback` state.
- The model picker shows the Primary cooldown, current usable fallback, remaining automatic-check time, and a `Primary retry` action.
- The action reserves the next real foreground request once, creates no synthetic provider request, and can be cancelled before use.
- The reserved state is visible as `Primary next` or equivalent non-color-only text.
- Agent response content and message bubbles do not gain a fallback marker.
- Mobile provides the same status and recovery action in the model-selection flow without clipped controls or unreachable content.

### REQ-7. Existing configuration and Workspace defaults

Existing Agents retain equivalent one-candidate label behavior after upgrade, and Workspace defaults continue to affect only newly created Agents.

**Acceptance criteria**

- Every existing selectable label remains usable with its previous physical model and settings as its Primary candidate.
- Existing main and Lightweight label selections remain equivalent after upgrade.
- New Agents receive independent copies of the current Workspace label chains and candidate settings.
- Later Workspace default changes do not mutate existing Agent chains.
- Existing unavailable-model diagnostics remain applicable to an individual saved candidate.

### REQ-8. Provenance, diagnostics, and observable validation

Azents retains enough bounded state to explain and validate fallback behavior without exposing secrets or adding routing text to the response body.

**Acceptance criteria**

- Successful model output retains the actual physical candidate provenance separately from requested label intent.
- Active and terminal state can distinguish cooldown, incompatibility, quota failure, and chain exhaustion using user-safe diagnostics.
- Metrics can measure fallback success, progression latency, chain exhaustion causes, Primary retry outcomes, and repeated same-candidate quota calls.
- Logs and API responses exclude credentials, raw provider bodies, prompts, model output, and unbounded provider diagnostics.
- Required automated verification covers configuration, main sampling, compaction, title generation, cooldown sharing, half-open concurrency, restart/handover, Primary retry, terminal exhaustion, and desktop/mobile recovery presentation.

## Fixed Constraints

- PostgreSQL remains the durable recovery authority; Redis remains optional volatile coordination and may be restored empty.
- Existing Agent, Session, Workspace, authorization, transcript, and provider-failure ownership boundaries remain authoritative unless an accepted ADR explicitly replaces one.
- Provider calls and other external I/O do not occur while a database transaction is open.
- Provider SDK automatic retries remain disabled where the current execution boundary owns retry.
- Git-tracked artifacts and user/operator-facing service text are English and contain no private provenance or credentials.

## Open Assumptions

- The current provider-failure taxonomy continues to identify account, plan, credit, and billing exhaustion accurately enough to trigger fallback.
- Actual user behavior data is not yet available; post-release evidence is needed to validate whether the compact recovery state is sufficiently discoverable and reduces manual model changes.
- Public API transition and storage representation are technical design decisions and must not introduce a second source of truth.

## Confirmation

Confirmed by the requester on 2026-09-12 before ADR decisions were accepted. The requester delegated ordinary reversible technical decisions and retained only decisions with material public-contract, durable-authority, or failure-recovery consequences for explicit review.
Later on 2026-09-12, the requester accepted the public v1 clean cutover and delegated all remaining
technical decisions and Design approval. The background-operation wording was then clarified to
preserve the already confirmed Workspace-shared physical cooldown while keeping foreground Session
intent and reservation state unchanged.
