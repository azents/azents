---
title: "Composer Model Execution Options Requirements"
created: 2026-09-08
implemented: 2026-09-08
tags: [models, frontend, engine]
document_role: primary
document_type: requirements
snapshot_id: execution-260908
---

# Composer Model Execution Options Requirements

- Snapshot: `execution-260908`
- Document reference: `execution-260908/REQ`

## Problem

Users cannot directly choose a supported model's faster execution mode from the conversation composer while retaining their chosen model and reasoning effort. Static model abilities and immediately switchable execution preferences are distinct concepts.

## Primary Context

### Primary Actor

A Workspace member authorized to write to an Agent Session.

### Primary Scenario

The member selects an available model in the Chat composer, sees that model's execution options, enables Fast with an explanation of its cost implications, submits work, and can disable Fast for subsequent work without leaving the conversation or changing the model.

## Supporting Scenarios or Effects

- The same interaction works for supported OpenAI API-key and ChatGPT OAuth models while preserving their distinct billing and authentication behavior.
- Maintainers can add another provider/model's switchable execution option without treating it as a built-in tool or redesigning the composer.

## Goals

- Direct, understandable, reversible on/off control in the composer.
- Separate execution-option class from static model abilities, built-in tools, and reasoning effort.
- Consistent persisted user intent and immutable already-prepared execution.

## Non-Goals

- New built-in tool controls or changes to image generation behavior.
- An arbitrary provider request editor, global Fast flag, or lower-capability model substitution.
- Additional unimplemented provider features, new billing infrastructure, or guaranteed latency improvements.
- Automatic enabling of premium execution for existing Sessions.

## Requirements

### REQ-1. Separate switchable execution options

Model execution options form a distinct class of user-controlled choices. Fast is the first option; the structure supports future model/provider-specific options independently of static abilities.

**Acceptance criteria**

- Adding another implemented option can reuse discovery, validation, state, and composer presentation boundaries.
- Fast is not represented as an image-generation or built-in-tool capability and does not change those settings.
- Unknown/unimplemented options cannot cause arbitrary provider parameters to be submitted.

### REQ-2. Composer control

Users can directly enable and disable supported options from the Chat composer without opening Agent settings or sending a message solely to change the option.

**Acceptance criteria**

- Supported options have visible on/off state, keyboard-operable controls, and usable narrow-screen layout.
- The same controls are available before the first message and in an existing Session.
- A failure to save is shown and does not falsely show a persisted successful change.
- Selection changes retain only options supported by the newly selected model; unsupported settings do not leak to another provider.

### REQ-3. Fast behavior and cost clarity

Fast requests faster processing of the selected supported OpenAI model through either API-key or ChatGPT OAuth authentication without reducing reasoning effort or changing model identity.

**Acceptance criteria**

- Fast starts off; enabling is explicit and reversible.
- The control explains additional API cost or ChatGPT usage/credits as appropriate, without a fixed speed or billing guarantee.
- Supported on/off selections are transmitted correctly on all relevant sampling transports.
- Provider rejection remains visible through existing failure handling rather than silently retrying in a different user-selected mode.
- Usage/cost presentation does not knowingly label a standard-rate estimate as a verified premium charge.

### REQ-4. Execution intent lifecycle

An accepted option change applies to future work consistently with existing Session model-profile controls; it does not mutate an in-flight prepared request.

**Acceptance criteria**

- Reloading an existing Session shows the saved choice.
- Submitted and queued inputs carry the chosen options; retry/recovery preserves the prepared options.
- Already-prepared work retains its original settings after the composer changes.
- Fresh Sessions and unrelated model targets do not acquire premium settings implicitly.
- Existing authorization and model-selection boundaries remain enforced server-side.

## Fixed Constraints

- Deliver investigation, product and technical design, implementation, tests, and Living Spec updates in one PR.
- Use official SDK request paths and preserve existing provider/authentication separation.
- Public repository artifacts are English and contain no private provenance or credentials.
- Implement without intermediate requester approval pauses; report decisions and evidence for final requester review.

## Open Assumptions

- Faster execution availability and entitlement can change at the provider; advertised support does not guarantee account quota, latency, or acceptance.
- No actual user study or comparative paid latency benchmark has been performed.

## Confirmation

The requester explicitly requested this scope and delegated product and technical decisions, including unresolved implementation questions, on 2026-09-08 KST. The requester additionally required a separate immediately switchable option class and composer on/off. This snapshot records that delegated scope before ADR decisions; final requester review is deferred until implementation completion as instructed, not represented as a completed review of this document.
