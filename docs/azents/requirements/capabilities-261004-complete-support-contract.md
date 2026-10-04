---
title: "Complete Model Capability Support Requirements"
created: 2026-10-04
implemented: 2026-10-04
tags: [backend, engine, frontend, model-catalog, reliability]
document_role: primary
document_type: requirements
snapshot_id: capabilities-261004
---

# Complete Model Capability Support Requirements

- Snapshot: `capabilities-261004`
- Document reference: `capabilities-261004/REQ`

## Problem

Supported model features can disappear between provider information, stored model choices, product presentation, and requests. Repeated symptom-specific repairs have not established consistent end-to-end behavior. In particular, known function-tool support has been represented as unknown and conservative display values have become execution gates.

## Primary System Outcome

Model capability information accurately represents the supported features and limits of the chosen model on its configured provider route, and all product consumers apply the same resolved support contract.

## Supporting Scenarios or Effects

- Function-tool support remains present for models whose provider contract supports it.
- Rich input, reasoning, structured output, sampling and other model controls survive the complete authorized request path when supported.
- Internal model executions use the same capability rules as foreground executions.

## Goals

- Correct the implementation comprehensively, replacing incorrect implementation units when necessary.
- Establish real-model evidence in addition to code-level regression tests.
- Eliminate confusing unknown/unverified capability states from the final supported-feature contract and its user-facing presentation.

## Non-Goals

- Shipping a separate symptom-only hotfix before the complete correction.
- Silently selecting a different model, adding a vision helper, or changing quota fallback order.
- Unapproved production mutation, credential rotation, deployment or merge.
- Claiming that an unavailable live verification lane has passed.

## Requirements

### REQ-1. One definitive supported-feature interpretation

The final supported-feature set is authoritative: inclusion means support and omission means no support. The product must not introduce an unknown/unverified feature state as a substitute for producing a correct supported-feature set.

**Acceptance criteria**

- Product display, configuration validation and execution agree on the final supported features.
- No unknown/unverified capability badge is introduced.
- Original information gaps do not falsely remove a feature established by the applicable provider/model contract.

### REQ-2. Complete capability and limit coverage

Audit all configured provider routes and every feature represented by the model-capability system rather than just function calling or images.

**Acceptance criteria**

- Coverage includes function tools, parallel calls, strict tool schemas, structured responses, reasoning levels/defaults/summaries, sampling controls, input/output forms, built-in tools, execution options and limits.
- Every existing producer declaration and consumer has a recorded disposition.
- Actual lack of implementation is distinguished in diagnostic evidence from a model's factual lack of support without creating an ambiguous final support state.

### REQ-3. Correct end-to-end behavior

Supported features and user intent remain correct through selection, saving, display and actual model requests, including internal model operations.

**Acceptance criteria**

- Known tool-call support is retained for supported models rather than merely allowing a request despite incorrect metadata.
- Actual sent request settings determine conditional admission; discarded or overridden settings cannot authorize a feature.
- Unsupported features are not silently advertised or enabled.
- Existing exact model identities, settings, ownership and quota fences remain intact unless the requester explicitly changes them.

### REQ-4. Replace structurally incorrect implementation

Review the implementation approach itself. Replace responsibilities, transformations or state models that create recurring omissions rather than accumulating isolated field fixes.

**Acceptance criteria**

- Audit findings identify complete affected units and their replacement boundaries.
- Redundant sources of capability authority and lossy consumer interpretations are removed from the corrected path.
- Regressions cover the root failure classes across the relevant consumers, not just the originally reported examples.

### REQ-5. Real model information verification

Verify corrected values against researched official model/provider information and actual available model-list responses, then compare final values and requests.

**Acceptance criteria**

- Record expected values and their original source before comparing them to the implementation output.
- Compare model information with stored and selected capabilities, UI interpretation and actual SDK request fields.
- Run bounded live model verification where authorized and feasible, clearly separating serializer checks from provider acceptance.
- Report inaccessible credentials, account-specific differences and unverified lanes separately; do not count them as success.

### REQ-6. Preserve pre-Pydantic ultra handling

Keep the reasoning preset behavior that existed before the Pydantic inference cutover. This repair must not introduce a new selectable or directly dispatched `ultra` reasoning effort.

**Acceptance criteria**

- Original provider declarations retain `ultra` as source evidence.
- The selectable reasoning domain remains the existing seven canonical values; an `ultra` declaration is excluded rather than mapped to `max` or another level.
- UI inputs, saved settings and request admission use the existing canonical domain.
- Regression evidence compares the repaired path with the pre-cutover parser and its existing fixture.

## Fixed Constraints

- Preserve configured model identity and ordered quota fallback; incompatible options do not justify dropping the assigned model.
- Preserve existing authorization, owner-generation, publication and data-integrity fences.
- Preserve immutable historical execution/provenance and adopted historical design records.
- Use provider/account scope and documented contracts; model-name similarity and SDK defaults alone do not establish support.
- No production writes, catalog refresh, restart, merge or deployment without separate authorization.

## Open Assumptions

- Some provider/account routes may be unavailable for live verification. Static contract coverage is still required, with remaining live gaps explicitly reported.
- The corrected supported-feature set concerns the product's chosen execution route; richer standalone provider APIs do not automatically add unimplemented product features.

## Confirmation

The requester explicitly instructed a complete correction on 2026-10-04, cancelled the separate hotfix, required final support-list semantics without unknown/unverified capability states, required implementation reconsideration and replacement when necessary, and required actual model-information verification beyond code tests. The requester subsequently required `ultra` handling to match the pre-Pydantic implementation exactly. This document records those instructions; it does not claim approval of implementation mechanisms not yet researched.
