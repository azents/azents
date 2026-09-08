---
title: "Composer Model Execution Options Decisions"
created: 2026-09-08
tags: [models, architecture, engine]
document_role: primary
document_type: adr
snapshot_id: execution-260908
---

# Composer Model Execution Options Decisions

- Snapshot: `execution-260908`
- Requirements: [execution-260908/REQ](../requirements/execution-260908-model-execution-options.md)
- Mode: Autonomous; technical decision owner: delegated technical interviewee.

## Material Decision Map

- D1: Definition, support, and user-intent authority — accepted.
- D2: Session, queued input, prepared execution, retry, and inheritance lifecycle — accepted.
- D3: Provider support evidence, wire mapping, failure and cost semantics — accepted.
- D4: Composer projection, persistence, and model transition boundary — accepted.

Fixed outcomes: separate switchable execution-option class, Fast first, composer on/off, API/OAuth distinction, default off, one PR. Identifier/file layout and equivalent local helpers are implementation-owned details.

## D1. Separate execution-option definitions, supported snapshots, and enabled intent

- ID: `execution-260908/ADR-D1`
- Requirements: REQ-1, REQ-2, REQ-3, REQ-4.
- Accepted on: 2026-09-08.

Use a code-owned typed registry of execution-option definitions, a top-level `supported_execution_options` snapshot alongside static model capabilities, and a per-inference-profile `enabled_execution_options` selection. Definitions own known IDs, boolean control semantics, human-readable metadata, and bounded provider translation. Fast is not a built-in tool or member of `ModelCapabilities`.

Catalog projection records supported IDs and selection normalization copies them into `AgentModelSelection`. Runtime uses that selection snapshot, without catalog or provider discovery. All newly constructed snapshots explicitly serialize support. Historical selection JSON that lacks the new support field is read as an empty supported set; this is a narrow schema-evolution boundary, not support inference or a legacy request path. Existing catalog/selection snapshots gain support through normal resync and reselection. No broad historical JSON backfill infers capability from raw metadata.

Rejected: a global Fast boolean (cannot represent model-specific extension); arbitrary provider-option dictionaries (unsafe unbounded request surface); runtime extraction from source metadata (second authority and snapshot drift); treating execution preferences as static or built-in-tool capabilities (contradicts REQ-1).

Risks: existing saved model selections need refresh/reselection before newly supported options appear. This preserves snapshot authority and avoids silently enabling premium behavior. Additional option classes require implemented support projection, validation, provider translation, and tests rather than just an ID declaration.

## D2. Persist execution intent and freeze prepared work

- ID: `execution-260908/ADR-D2`
- Requirements: REQ-2, REQ-3, REQ-4.
- Accepted on: 2026-09-08.

Carry enabled option IDs through requested, Session-applied, message-applied, queued mailbox, original Run, and prepared inference snapshots. Composer profile replacement updates future fresh preparation only. Current provider calls and retries/recovery use their frozen original settings. Historical absence maps to all-off; new constructors supply the field explicitly. Persisted non-empty intent requires its corresponding model label.

Draft model switching intersects choices with the new model's supported IDs. Submitted explicit selections are validated, not silently intersected: if later Agent configuration makes queued intent unsupported, preparation fails through the deterministic invalid-profile boundary. Implicit parent inheritance may retain only supported options when changing targets; full-history same-target inheritance retains the complete prepared choice. Title and compaction calls use their own all-off options rather than inheriting premium sampling preferences.

Rejected: reading only mutable Session state at provider-call time (changes queued/retry intent); changing the active network request (violates immutable preparation); silently dropping explicitly accepted options (changes requested mode).

Risks: every REST/live/idempotency/profile-copy boundary must preserve the field. UI applied intent can differ from currently prepared execution and must not present future intent as the current call's provenance.

## D3. Reviewed provider support and bounded service-tier translation

- ID: `execution-260908/ADR-D3`
- Requirements: REQ-1, REQ-3, REQ-4.
- Accepted on: 2026-09-08.

The semantic ID is `fast`. OpenAI API support is an exact reviewed identifier list from the official Fast pricing table; aliases or dated variants not independently reviewed fail closed. ChatGPT OAuth support comes only from current account-catalog `service_tiers` entries declaring `priority` or `fast`; absent or empty support means unavailable. Do not infer support from model prefixes, pricing metadata alone, static abilities, or legacy speed metadata.

Enabled Fast maps to `service_tier=priority` for both OpenAI API-key and ChatGPT OAuth sampling. Disabled Fast on a supported API model explicitly sends `default` to override provider-project premium defaults. Disabled ChatGPT Fast omits the field following the verified Codex backend request semantics. Unsupported models/providers receive no service tier. Auxiliary title/compaction remain independently off.

Provider rejection retains the same prepared option through normal retry. No inline standard fallback or model substitution is introduced. Cost estimates follow the actual returned tier; normalize a returned `fast` alias for the pricing library and leave unknown premium pricing unset rather than charging at standard rates. ChatGPT estimates remain API-price estimates, not subscription credits or verified billing.

Evidence: official OpenAI Fast mode and pricing documentation reviewed 2026-09-08; Codex commit `530383e36de9c74cd79177a0c31d35609019134f`, `protocol/src/config_types.rs`, `protocol/src/openai_models.rs`, and `core/src/client.rs`. Model eligibility does not guarantee account entitlement, quota, regional support, latency, or successful requests.

Rejected: prefix support guesses, third-party OpenAI-compatible provider enablement, raw pricing-as-entitlement, legacy speed fallbacks, implicit premium project defaults on explicit off, and standard-rate estimates for unknown premium usage.

## D4. Immediate atomic composer control and explicit presentation projection

- ID: `execution-260908/ADR-D4`
- Requirements: REQ-1, REQ-2, REQ-3, REQ-4.
- Accepted on: 2026-09-08.

Render generic boolean option controls beside composer model/effort selection. Existing Sessions immediately submit the complete displayed profile through the existing model-profile PUT, including any displayed draft model/effort choice. The operation is atomic, requires no second Apply click, and has saving/error/revert state. New Sessions keep local draft choices until first run-producing input. Model changes intersect draft options with new support, while the server independently validates submitted options.

Persist support and enabled IDs only. Expose `execution_option_definitions` in explicit public response DTOs using the code-owned registry and provider context, with id, label, description, qualitative cost hint, and boolean control kind. Keep presentation fields out of persisted `AgentModelSelection`, including Pydantic computed fields that could leak into stored JSON. Known definitions remain available to render historical option labels when current support disappears. Generated clients consume this projection without a new endpoint.

Rejected: an extra Apply step for the toggle, a second browser preference authority, silently toggling the previously applied model instead of the displayed model, and duplicated provider-specific control logic.

Accepted UX consequence: toggling an option also applies a pending displayed model/effort change. Test this explicitly and preserve current authorization and read-only gates. Existing built-in tools and Agent settings controls remain unchanged.
