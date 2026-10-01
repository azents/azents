---
title: "Provider-Library Replacement Requirements"
created: 2026-09-30
updated: 2026-09-30
tags: [inference, engine, model-catalog, migration]
document_role: primary
document_type: requirements
snapshot_id: inference-260930
---

# Provider-Library Replacement Requirements

- Snapshot: `inference-260930`
- Document reference: `inference-260930/REQ`

## Problem

The current shared provider dependency couples Azents to its upstream SDK version constraints, including code paths that do not use it for inference. Replacing only the sampling call would leave dependencies in title generation, compaction, usage and cost reporting, model catalogs, context limits, and failure handling. A replacement must remove the executable dependency without losing the currently supported provider and conversation behavior.

## Primary Context

### Primary System Outcome

Azents can perform all currently supported conversation-model operations without the current shared provider package being installed, while existing integrations, saved model selections, conversations, execution controls, and observable provider behavior remain usable.

## Supporting Scenarios or Effects

- Maintainers can update directly used provider SDKs without version constraints imposed by the retired package.
- Users can continue existing conversations and switch supported providers without rewriting their conversation history.
- Model discovery, capability selection, context displays, compaction, and usage reporting continue to agree with their authoritative inputs.

## Goals

- Remove the executable dependency completely, including indirect use outside inference.
- Preserve all currently supported provider and credential variants.
- Preserve conversation continuity, tools, execution control, safe failures, and usage reporting.
- Make replacement and removal verifiable rather than relying on library-level compatibility claims.

## Non-Goals

- Replacing the Azents execution engine or changing its user-facing tool, scheduling, approval, retry, or persistence behavior.
- Adding providers, credentials, built-in tools, modalities, or capabilities that Azents does not currently support.
- Requiring migration of already-independent inference paths merely to make every provider use the same implementation.
- Redesigning integration setup, model selection, subscription usage, or image-generation functionality.
- Rewriting historical conversation artifacts or implemented documentation solely to remove old names.
- Treating removal of an executable package as automatic authorization to delete historical model-source data or change model visibility policy.
- Implementing or deploying changes during this design exercise.

## Requirements

### REQ-1. Complete executable dependency removal

All supported conversation-model operations must work without the retired provider package, including operations whose inference is already independent of that package.

**Acceptance criteria**

- Sampling, title generation, and compaction can execute for each in-scope route without the retired package installed.
- Usage and cost reporting, model catalog synchronization and reads, context-limit resolution, and model failure handling do not require imports or runtime access to the retired package.
- The resolved application dependency graph contains no retired package, and application startup plus required deterministic verification succeed without it.
- Updating a directly used SDK no longer encounters a dependency constraint contributed by that package. Constraints from other remaining dependencies are reported separately.

### REQ-2. Supported provider and credential continuity

Existing integrations and saved model selections must remain usable with their current credential, configuration, and account-visibility semantics.

**Acceptance criteria**

- Coverage includes OpenAI API key, ChatGPT OAuth, Anthropic API key, Gemini API key, AWS Bedrock, Google Vertex AI, xAI API key, xAI OAuth, OpenRouter API key, and Kimi OAuth for their currently supported model routes.
- Sampling, title generation, and compaction retain the existing route eligibility, selected model, supported settings, and operation-specific failure behavior.
- Existing integration ownership, enabled/deleted handling, credential refresh, reauthentication, account identity, and cloud configuration continue to apply.
- xAI API-key and OAuth integrations retain distinct visibility, billing, and entitlement behavior; success for one credential variant does not establish support for the other.
- No new user reconfiguration or reconnection is required solely because the executable provider dependency is replaced.

### REQ-3. Conversation continuity and safe native replay

Existing conversations must remain readable and usable for continued model execution. Provider-specific replay must remain subordinate to authoritative conversation semantics and existing compatibility restrictions.

**Acceptance criteria**

- An existing conversation can continue after the replacement and after a supported provider or model change without rewriting its stored history.
- Provider-native data is replayed only when the existing exact compatibility conditions are satisfied; otherwise the conversation is reconstructed from its authoritative semantic history.
- Reasoning signatures, encrypted or redacted reasoning, tool identity, and supported multimodal content are retained where the compatible route requires them, without exposing opaque content as visible reasoning text.
- Adapter changes do not duplicate messages, lose completed tool results, or re-execute historical tool calls.
- Existing behavior is grounded in the [Conversation Spec](../spec/domain/conversation.md) and [Agent Execution Loop Spec](../spec/flow/agent-execution-loop.md), not in a replacement library's ability to deserialize a payload.

### REQ-4. Supported tools and provider output fidelity

The replacement must preserve the tool and output semantics that Azents currently exposes for each supported route, without advertising unsupported functionality.

**Acceptance criteria**

- Supported client-tool names, declarations, argument semantics, streaming assembly, call/result identities, and custom-versus-JSON-function behavior remain effective.
- Supported provider-hosted tool activity, results, references, excerpts, and stable metadata remain available to conversation history and presentation to the extent they are currently exposed.
- Client-executed built-ins and provider-hosted tools retain their existing execution ownership and selectable capability behavior.
- Provider-specific declaration limits and compatibility rules remain enforced for applicable routes.
- Library-only support for a modality, tool, or model profile does not enable a capability that the saved selection and current Azents policy do not authorize.

### REQ-5. Execution, stream, and recovery correctness

The replacement must preserve the existing observable model-operation lifecycle, timeout, cancellation, retry, and recovery contracts.

**Acceptance criteria**

- Partial output, an unsuccessful response, or a stream that fails the existing completion contract does not become a successful completed turn merely because iteration ended or content was produced.
- Connect, parsed-event idle, and absolute-attempt deadlines retain their current scope, classification, cleanup, and operation-specific consequences.
- User Stop retains precedence over concurrent timeout and failure, uses the ordinary interruption behavior, and does not produce failed-run retry or stopped-run replay state.
- Classified provider failures retain the complete configured Run retry budget, bounded attempt history, current retry progression, and recovery behavior. Unclassified internal errors retain their separate handling.
- Retries rebuild current authoritative invocation inputs and preserve existing model-candidate progression and operation-specific behavior; hidden retry or continuation behavior cannot silently bypass these contracts.
- Title failure preserves the deterministic fallback title; blocking compaction and sampling retain their existing error and retry behavior.

### REQ-6. Model catalog and context behavior preservation

Catalog discovery, capability selection, saved selections, and effective context limits must remain consistent with the current provider/account and metadata authority rules.

**Acceptance criteria**

- Account/provider-authoritative model visibility remains authoritative. A missing optional metadata match does not hide a model that currently remains selectable.
- Unknown capabilities remain conservative, including explicit reasoning-effort support, built-in tools, modalities, and supported execution options.
- Catalog reads do not introduce remote discovery or source-ingestion calls. Failed synchronization retains the last successful snapshot and the current configuration-generation eligibility behavior.
- Source validation, failure handling, publication fencing, and protection against unexplained destructive model-set reductions remain effective for whichever metadata source is authorized in the design.
- Existing saved selections do not silently change when catalogs or library profiles change, except for the currently documented call-time transport constraint rules.
- Provider default and maximum input windows, user caps, main/compaction limits, and the auto-compaction threshold continue to produce a consistent runtime and UI result. Missing metadata retains the existing documented fallback behavior unless separately authorized.
- Existing catalog authority and context semantics are grounded in the [Model Catalog Spec](../spec/domain/model-catalog.md) and Agent Execution Loop Spec.

### REQ-7. Usage, cost, and safe diagnostics

Users and operators must retain meaningful usage and cost information and actionable failures without disclosure of sensitive provider data.

**Acceptance criteria**

- Supported input, output, total, cached-input, cache-write, and reasoning usage remain distinguishable when the provider supplies them; progressive and final usage retain their existing accumulation semantics.
- Provider-reported charges and price-based estimates are not conflated, and the design identifies the applicable price or charge authority for each route.
- Unknown or invalid cost remains unknown rather than becoming zero. Unsupported priority pricing does not become a fabricated standard-price estimate.
- Cost calculation does not require model-output content.
- Durable errors and user/operator diagnostics retain the common bounded and redacted failure contract. Credentials, authorization headers, cookies, raw provider bodies, stream frames, opaque reasoning, and untrusted exception serialization do not cross that boundary.
- Introducing the replacement does not silently enable capture or export of prompts, outputs, or credentials through an additional tracing system.

### REQ-8. Verifiable cutover without collateral removal

The completed replacement must have evidence for both preserved behavior and the absence of obsolete executable dependencies, without deleting still-authoritative state or affecting unrelated functionality.

**Acceptance criteria**

- Verification covers user-visible behavior end to end, with deterministic provider fixtures and focused lower-level tests for provider-specific transformations and failure boundaries.
- E2E verifies core user-visible behavior and real product boundaries. Complex condition combinations, provider/SDK transformation details, and boundary-value matrices belong in focused unit or contract tests; the evidence mapping still accounts for every required behavior.
- E2E execution time must remain strictly below 110% of the comparable main baseline. A slowdown of 10% or more rejects the delivery. Measurements use equivalent execution conditions and include added fixture/setup/teardown work rather than hiding it through extra runners or prerequisite stages.
- Provider, credential, supported-tool, history-continuation, timeout, Stop, retry, catalog, context, and usage cases are mapped explicitly to requirements and evidence.
- Mock or offline probes are labeled as such; they are not represented as successful authenticated provider integration. Unverified live credential or transport prerequisites remain explicit feasibility conditions.
- The removal inventory accounts for runtime code, tests and fixtures, dependency and maintenance configuration, model identifiers, current documentation, and affected persistence/API/generated surfaces. Each has a replacement or an explicit remaining authority.
- Existing historical source snapshots and conversation artifacts remain usable under their authorized contracts. Any required persistence or API transition is specified and verified rather than achieved by editing an already-executed migration.
- Image-generation catalogs and unrelated provider features continue to work where they share catalog state or identifiers with conversation-model functionality.

## Fixed Constraints

- Existing provider identities and observable behavior remain the baseline unless the requester explicitly authorizes a changed requirement.
- Direct dependency pins owned by Azents may be adjusted; the current pin set is not itself a feasibility requirement.
- Existing transcript authority, exact native replay restrictions, credential isolation, safe failure handling, and execution-control contracts remain in force.
- Historical implemented Requirements, accepted ADRs, Designs, and executed migrations are not rewritten as dependency cleanup.
- This snapshot is design-only until the requester separately authorizes implementation.

## Open Assumptions

- The confirmed primary outcome is removal of the executable dependency. External metadata-source policy is recorded separately in [inference-260930/ADR](../adr/inference-260930-provider-replacement.md). Complete independence from that external data source is not a confirmed requirement; any outcome change requires requester confirmation before the affected design decisions.
- The replacement's transport viability is not yet established for every credential/model route, especially xAI OAuth and cloud-hosted variants. This is a feasibility question, not permission to remove a supported route.
- Any material change to catalog persistence names, exposed source identity, or runtime model identifiers requires a documented compatibility/removal decision; package removal alone does not authorize destructive state cleanup.

## Confirmation

Confirmed by the requester on 2026-09-30 (KST) before ADR and design decisions began. Confirmation covers REQ-1 through REQ-8, goals, non-goals, fixed constraints, and the explicit distinction between executable package removal and public metadata-source policy. It does not authorize implementation or deployment.

The requester added the REQ-8 verification-quality clarification on 2026-09-30 (KST): E2E at least 10% slower than main is rejected, complex conditional tests belong in unit tests, and E2E verifies core behavior. This clarification changes test ownership and delivery acceptance, not the approved provider behavior or M1–M13 material mechanisms.
