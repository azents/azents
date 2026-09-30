---
title: "Ultrafast Model Execution Requirements"
created: 2026-09-30
implemented: 2026-09-30
tags: [models, frontend, engine]
document_role: primary
document_type: requirements
snapshot_id: ultrafast-260930
---

# Ultrafast Model Execution Requirements

- Snapshot: `ultrafast-260930`
- Document reference: `ultrafast-260930/REQ`

## Problem

Azents users can opt into Fast processing for supported models but cannot choose
Ultrafast through the existing conversation controls. An Ultrafast choice must
preserve explicit user intent and avoid misleading premium-cost estimates.

## Primary Context

### Primary Actor

A Workspace member authorized to write to an Agent Session.

### Primary Scenario

The member selects an available supported model in the conversation composer,
chooses Ultrafast after seeing its premium-usage explanation, submits work with
that choice, and can return to ordinary or Fast processing for subsequent work
without changing the model, reasoning effort, or tools.

## Supporting Scenarios or Effects

- The same user-controlled capability works through existing OpenAI API-key and
  ChatGPT subscription integrations where the provider supports it.
- Before-first-message and existing-Session controls remain consistent.
- Session reload, queued input, retry, recovery, and inherited work continue to
  follow the existing model-profile lifecycle.
- Existing ordinary and Fast choices remain usable without a settings migration
  that implicitly enables Ultrafast.

## Goals

- Explicit and reversible Ultrafast selection for supported models.
- One unambiguous processing-speed preference at a time.
- Consistent behavior across supported integrations and sampling transports.
- Honest usage and cost presentation under the existing dependency versions.

## Non-Goals

- Dependency upgrades, authentication changes, or a new provider integration.
- An arbitrary provider-parameter editor or additional premium processing modes.
- Guaranteed latency, provider entitlement, remaining quota, or a paid speed
  benchmark.
- Changing model identity, reasoning effort, built-in tools, or image-generation
  behavior when changing the processing-speed preference.
- Automatically enabling premium processing for existing users or Sessions.
- Applying premium sampling preferences to title generation or compaction.
- A new subscription billing, credit conversion, or financial accounting system.

## Requirements

### REQ-1. Supported-model availability

A user can choose Ultrafast only when the selected model is advertised as
supporting it for the integration in use.

**Acceptance criteria**

- The capability is available through both existing OpenAI API-key and ChatGPT
  subscription integrations for supported models.
- A supported model can expose Ultrafast independently of its Fast availability.
- Missing or unsupported provider information does not implicitly advertise
  Ultrafast, and unrelated providers do not acquire support.
- Advertised support is not presented as a guarantee of account entitlement,
  quota, regional acceptance, or achieved latency.
- Existing saved model selections retain their current support behavior until
  refreshed through the established catalog and model-selection workflow.

### REQ-2. Explicit and exclusive speed selection

Users can select ordinary, Fast, or Ultrafast processing directly in the
conversation composer, subject to the model's supported choices.

**Acceptance criteria**

- At most one premium speed preference is active at a time; Fast and Ultrafast
  cannot be enabled simultaneously.
- Ultrafast is initially off and requires explicit user choice or an existing
  authorized profile-inheritance flow.
- Users can enable or disable Ultrafast without sending a message solely to
  change the preference or opening Agent settings.
- Keyboard operation and narrow-screen use remain supported before the first
  message and in an existing Session.
- A failed save is shown without falsely representing the change as persisted.
- A model change does not retain an unsupported speed preference under the
  existing composer-normalization rules.

### REQ-3. Selected-model execution and visible rejection

Ultrafast requests faster processing of the selected model without changing the
user's other inference choices.

**Acceptance criteria**

- Selecting Ultrafast does not change model identity, reasoning effort, tools,
  authentication identity, or image-generation settings.
- Supported selections are transmitted correctly through all existing relevant
  sampling transports.
- Invalid, conflicting, or unsupported explicit speed selections fail through
  existing validation boundaries before provider invocation.
- Provider rejection follows existing failure handling rather than silently
  removing the preference or choosing another speed or model outside existing
  explicit profile and candidate-selection rules.
- Ordinary and Fast behavior remain unchanged when Ultrafast is not selected.

### REQ-4. Existing inference-profile lifecycle

An accepted Ultrafast preference follows the same lifecycle as existing Session
model-profile choices.

**Acceptance criteria**

- Reloading an existing Session restores its saved processing-speed preference.
- Submitted and queued work records the intended choice; an already-prepared
  active attempt is not mutated by a later composer change.
- A new automatic retry or recovery attempt uses the current Session-applied
  profile according to existing rules rather than introducing a second retry
  or speed-fallback policy.
- Existing parent/subagent inheritance and changed-target support filtering
  apply consistently to Ultrafast.
- Title and compaction operations retain their existing independent all-off
  premium behavior.

### REQ-5. Premium cost and usage honesty

Users receive an appropriate premium-usage explanation and are not shown an
ordinary-rate estimate as an Ultrafast charge.

**Acceptance criteria**

- API-key users see an additional API-cost explanation; subscription users see
  an additional usage/credit explanation without a fixed entitlement or speed
  guarantee.
- Cost estimation uses the processing mode actually served, not solely the
  requested preference.
- Unknown or unsupported premium pricing leaves the estimate unavailable rather
  than substituting ordinary pricing or a guessed multiplier.
- A missing estimate does not prevent successful model output from completing.
- API-price estimates are not presented as verified subscription billing or
  converted ChatGPT credits.

### REQ-6. Bounded adoption and regression safety

Ultrafast is added without requiring dependency upgrades or replacing unrelated
model-selection, authentication, or processing behavior.

**Acceptance criteria**

- The feature works with the provider SDK and model-provider dependency versions
  already used by the repository.
- Existing ordinary and Fast selections retain their meaning after deployment.
- Existing model visibility, authorization, saved-selection refresh, and
  inference-profile boundaries remain enforced.
- No broad change is made to unrelated providers, built-in tools, subscription
  usage display, or auxiliary model calls.

## Fixed Constraints

- Retain the existing dependency versions for this development snapshot; an SDK
  major-version migration is separate work.
- Preserve official provider-client request paths and the separation between
  API-key and subscription authentication and billing meanings.
- Preserve the current [model-catalog support and selection
  workflow](../spec/domain/model-catalog.md), [inference-profile
  lifecycle](../spec/domain/agent.md), and [premium-processing
  behavior](../spec/flow/chatgpt-oauth.md) except for adding the requested capability
  and mutually exclusive speed choice.
- Repository artifacts are English and contain no private provenance,
  credentials, or account-specific evidence.
- This request covers design only; implementation starts only after a separate
  requester instruction.

## Open Assumptions

- Provider support declarations, entitlement, quota, and regional restrictions
  can change; advertised support may still result in provider rejection.
- A live provider-verification run depends on an eligible test account and a
  separately authorized cost-bearing test scope. Deterministic non-live evidence
  does not establish a particular account's entitlement or measured speed gain.

## Confirmation

The requester explicitly confirmed the complete six-requirement scope on
2026-09-30 KST before this snapshot's ADR decisions and primary Design began.
Product scope and unresolved material technical decisions remain requester-owned;
implementation has not been requested.
