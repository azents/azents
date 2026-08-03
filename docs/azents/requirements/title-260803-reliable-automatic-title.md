---
title: "Reliable Automatic Session Title Requirements"
created: 2026-08-03
updated: 2026-08-03
implemented: 2026-08-03
tags: [session, title, llm, external-channel]
document_role: primary
document_type: requirements
snapshot_id: title-260803
---

# Reliable Automatic Session Title Requirements

- Snapshot: `title-260803`
- Document reference: `title-260803/REQ`

## Problem

Automatic Session title generation currently relies on an unconstrained text response from the Agent's lightweight model. Some models may return explanatory text instead of only a title. The saved model capability may explicitly report Structured Output support, explicitly report no support, or leave support unknown. Restricting the lightweight-model selection or switching to another model would reduce compatibility and violate the user's chosen model. External Channel invocation markup may also distract the title model even though it exists only to address the connected Agent.

## Primary Actor

A user whose new Agent Session receives an automatically generated title from the Agent's selected lightweight model.

## Primary Scenario

A human sends the first request for a new Session. Azents uses the Agent's existing lightweight model and its saved Structured Output capability to choose the title invocation mode. Explicit support uses only Structured Output. Explicit non-support uses only the existing plain-text mode. Unknown support tries Structured Output first and switches to the plain-text compatibility mode only when the endpoint explicitly rejects or cannot route that output contract or returns output that cannot be decoded through the requested schema. No branch changes the provider, integration, or model. A valid result replaces the deterministic initial title; otherwise the deterministic initial title remains. For an External Channel request, the title instructions tell the model to ignore invocation-only Bot or App markup while preserving request-relevant references.

## Supporting Scenarios

- A direct Web/API Session uses the same automatic-title prompt and output-mode behavior.
- A lightweight model recorded with explicit Structured Output support uses only the constrained-output mode.
- A lightweight model recorded with explicit Structured Output non-support uses only the current plain-text mode.
- A lightweight model with unknown Structured Output support first tries the constrained-output mode and may use the current plain-text mode when the endpoint explicitly rejects or cannot route that contract or returns output that violates the requested schema.
- A Discord or Slack invocation may contain invocation-only Bot or App markup together with other request-relevant user, role, or channel references.

## Goals

- Improve the output-format reliability of automatic Session titles without restricting lightweight-model selection.
- Preserve the Agent's exact selected lightweight provider, integration, and model throughout title generation.
- Preserve compatibility with models or endpoints that do not support Structured Output.
- Instruct the title model to ignore invocation-only External Channel identity markup while preserving request-relevant references.
- Make the title instructions internally consistent and less likely to elicit meta commentary.
- Preserve the existing best-effort, non-blocking automatic-title lifecycle and deterministic initial-title fallback.

## Non-Goals

- Selecting, configuring, or switching to a separate fallback model.
- Restricting the lightweight-model picker to Structured Output-capable models.
- Guaranteeing detection of every semantically poor, echoed, or unnatural title.
- Adding a new semantic title validator or prohibited-phrase catalog.
- Changing the current language-selection behavior or addressing an unobserved English-language bias.
- Parsing, storing, or deterministically removing invocation-specific provider references from the canonical message or title input.
- Changing manual-title precedence, the `auto_initial` to `auto_generated` ownership fence, or Discord thread-title projection semantics.
- Adding durable retry, recovery, reconciliation, backfill, or title-attempt state.

## Requirements

### REQ-1. Capability-directed same-model title generation

Automatic title generation must choose its output mode from the saved tri-state Structured Output capability while preserving the Agent's currently selected lightweight model.

**Acceptance criteria**

- Every title-generation attempt uses the exact provider integration and model in the Agent's effective lightweight-model selection.
- An explicit supported capability uses only the constrained-output contract. Failure does not trigger a plain-text compatibility attempt.
- An explicit unsupported capability uses only the existing plain-text title contract and does not attempt Structured Output.
- An unknown capability first uses the constrained-output contract. If the endpoint explicitly rejects or cannot route that contract or returns output that cannot be decoded through the requested schema, Azents switches to the plain-text compatibility mode using the exact same provider integration and model.
- Output-mode fallback never selects another model or provider integration.
- Authentication failure, rate limiting, timeout, cancellation, transport failure, and provider server failure do not trigger output-mode fallback.

### REQ-2. Compatible title result handling

Both output modes must preserve the existing automatic-title lifecycle and deterministic fallback behavior.

**Acceptance criteria**

- A successfully decoded non-empty title is normalized to the existing Session-title length and whitespace constraints.
- The plain-text compatibility result continues to use the existing plain-text title cleanup behavior.
- No new semantic validator is required for either output mode.
- An unknown-capability constrained-output attempt followed by an unsuccessful plain-text compatibility attempt leaves the matching `auto_initial` title unchanged.
- Title generation never delays or fails Session admission, wake, AgentRun creation, Agent execution, or ordinary External Channel delivery.

### REQ-3. Coherent title instructions

The automatic-title instructions must describe the desired title without contradictory rules or unnecessary meta framing.

**Acceptance criteria**

- The instructions do not prohibit a term that an included example requires, including legitimate summary-related wording.
- The request wrapper asks for a title from the request without describing the content as a "user prompt" that should itself be reported.
- Products, tools, filenames, and technical terms explicitly present in the request remain valid title content.
- Internal Agent actions or tools not present in the request are not introduced into the title.
- Structured Output owns the structured response envelope; the plain-text compatibility mode separately requires title-only plain text.
- The instructions tell the model to ignore platform markup used only to address the Agent, such as Bot or App mentions, while preserving references relevant to the user's request.
- Existing language-selection behavior and examples are not changed solely to address language bias.

### REQ-4. Existing title authority and projection compatibility

The reliability change must not alter existing Session-title authority or External Channel projection ownership.

**Acceptance criteria**

- Only the matching `auto_initial` title for the exact generation Event may be replaced by `auto_generated`.
- Manual title updates or clears remain authoritative over delayed generation.
- Discord thread-title projection is triggered only by the same successful automatic-title commit that triggers it today.
- Output-mode fallback does not add another Discord projection trigger, provider-title attempt, or durable projection state.

## Fixed Constraints

- Explicit Structured Output support uses only Structured Output.
- Explicit Structured Output non-support uses only plain text.
- Unknown Structured Output support tries Structured Output before plain text.
- The fallback changes only the invocation output mode; provider, integration, model, title source Event, and title ownership remain unchanged.
- An unknown-capability title operation performs at most one output-mode transition from Structured Output to plain text.
- The existing provider retry policy continues within the active output mode and does not create another mode transition.
- Capability metadata determines title invocation mode but does not restrict lightweight-model selection.
- The current language behavior remains unchanged.
- No semantic title validator is added.
- Invocation-only provider markup is handled only by title instructions; no invocation-reference state or deterministic removal path is added.
- Existing automatic-title failure isolation and title-authority fences remain unchanged.
- The implemented `title-260802` Requirements, ADR, and Design remain immutable historical authority.

## Open Assumptions

- For the unknown-capability branch, each supported provider path can expose enough typed failure or schema-decode evidence to distinguish an unsupported or unhonored Structured Output contract from authentication, capacity, timeout, transport, and server failures. The Design must mark any provider path without such evidence as conditional rather than broadening fallback to unrelated failures.
- The shared response helpers can express a provider-compatible, minimal single-field title schema without changing the Agent's ordinary model execution contract.

## Confirmation

Confirmed by the requester on 2026-08-03 before ADR and design decisions began.
The unknown-capability contract-rejection and schema-decode fallback boundary was
clarified by the requester on 2026-08-03 before ADR-D2 was accepted.
Prompt-only handling of invocation markup was clarified by the requester on
2026-08-03 before the Design was created.
