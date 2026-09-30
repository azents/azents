---
title: "Ultrafast Model Execution Decisions"
created: 2026-09-30
tags: [models, frontend, engine, architecture]
document_role: primary
document_type: adr
snapshot_id: ultrafast-260930
---

# Ultrafast Model Execution Decisions

- Snapshot: `ultrafast-260930`
- Document reference: `ultrafast-260930/ADR`
- Mode: Collaborative.
- Decision owner: the requester for unresolved material technical decisions.
- Product authority: the requester-confirmed
  [Requirements](../requirements/ultrafast-260930-ultrafast-execution.md).

## Context

The current model-execution option contract separates supported option IDs on
saved model selections from enabled option IDs on requested, Session-applied, and
prepared inference profiles. Public code-owned option definitions currently
advertise boolean control semantics. Fast is the only implemented option.

The confirmed Requirements add Ultrafast and require an exclusive processing-speed
choice while retaining current dependencies, support-discovery boundaries,
ordinary/Fast meaning, and inference-profile behavior. The material question
presented for decision was whether exclusivity extends that existing option
contract or replaces speed preferences with a dedicated single-value contract.

## Decision Map

### Fixed and derived outcomes

These consequences are disclosed, not reopened as new decisions:

- Existing OpenAI API-key and ChatGPT OAuth identities are retained. Support uses
  the existing provider-specific projection authority: reviewed exact model
  identifiers for API-key catalogs, account model metadata for ChatGPT OAuth.
- Supported options and enabled user preferences remain distinct concepts. A model
  can advertise both Fast and Ultrafast although a user can activate only one.
- Current saved-selection snapshots and their refresh workflow remain authoritative;
  runtime does not discover support from model names or refetch catalogs.
- Current dependency versions, official SDK request paths, model identity,
  reasoning effort, tools, and authentication separation remain unchanged.
- Already-prepared attempts remain immutable; retry/recovery and changed-target
  inheritance retain the current Session-profile rules.
- Title and compaction operations do not inherit premium sampling preferences.
- The current delegated pricing calculator does not support the actual Ultrafast
  service tier. Under REQ-5 and REQ-6, its premium estimate must remain unavailable
  rather than falling back to Standard rates, using a guessed multiplier, or
  introducing another pricing authority. A response actually served at an existing
  supported Standard/Fast tier retains that tier's ordinary estimation path.
- Provider rejection, quota, regional restrictions, and provider-side served-tier
  changes remain provider behavior; no new application speed downgrade is added.

### Material technical decisions

- **ADR-D1 — accepted:** extend the existing execution-option contract with
  code-owned exclusivity for the speed family. No material technical decision
  remains unresolved.

### Blocking product questions

None identified after confirmation of the six Requirements. If later feasibility
work exposes a user-visible scope conflict, that question returns to Requirements
rather than being treated as an implementation detail.

### Agent-owned local details

Exact field and helper names, file layout, generated-client commands, localized
copy, equivalent local normalization structures, responsive control styling, and
fixture composition are agent-owned. They must not create an additional source of
truth, runtime mode, fallback policy, or persisted contract.

## ADR-D1. Representation of exclusive speed selection

**State:** Accepted by the requester on 2026-09-30 KST.

**Authority:** `ultrafast-260930/REQ-1`, `REQ-2`, `REQ-3`, `REQ-4`, and `REQ-6`.

### Consequence-level question

Should an exclusive processing-speed preference extend the existing execution
option contract, or become a dedicated single-value contract with coordinated
state and interface conversion?

### Option A — extend the existing execution-option contract

Keep current supported/enabled option ID collections as the sole persisted and
request preference representation. Add Ultrafast and code-owned exclusivity
metadata for the speed family; server validation and composer presentation derive
that relationship from the same definition authority.

- Existing ordinary selections remain no enabled premium-speed ID; existing Fast
  selections retain the Fast ID; Ultrafast adds its implemented ID.
- A catalog may advertise several supported members of the family. An enabled
  profile may contain at most one member.
- The composer presents one exclusive speed choice without introducing a second
  persisted speed field or hardcoding a separate provider policy.
- Current profile/history formats remain in place, so existing ordinary/Fast
  snapshots do not require representational conversion solely for this feature.
- Public option definitions and generated schemas gain the relationship metadata;
  support validation and active-preference validation must be separated.

**Trade-off:** exclusivity is a checked relationship over collections, not enforced
solely by the storage field's shape. The authoritative server validation must cover
all explicit input, profile, inheritance, and provider-lowering boundaries.

### Option B — introduce a dedicated single-value speed contract

Make one speed value the sole authoritative preference for ordinary/Fast/Ultrafast
selection. Coordinate request/response schemas, persisted profiles, prepared
snapshots, and existing selection/history readers around that contract, while
retaining current support-discovery authority and user-visible meanings.

- The speed field itself can hold only one selected value.
- Existing ordinary/Fast states require an explicit semantics-preserving conversion
  strategy; historical and active prepared profiles must remain readable with
  equivalent meaning.
- Public and generated interfaces, event/profile serialization boundaries, Session
  storage, and inheritance/retry readers have a broader transition surface.
- Adoption must have one canonical authority, not indefinite dual fields, dual
  writes, or an unrequested legacy fallback.
- Detailed conversion and rollout feasibility must be validated if this option is
  selected; selection does not authorize loss or mutation of prepared execution
  meaning.

**Trade-off:** shape-level exclusivity is stronger, but the API/state transition is
substantially broader than adding one supported speed option.

### Recommendation presented before the decision — Option A

The existing execution-option flow already owns support, explicit preference,
persistence, inheritance, retry, and provider translation. Extending it confines
this feature to that authority and avoids a new speed-specific state source and a
wide historical-format transition. A public code-owned exclusivity relationship
also lets the composer and backend use the same policy rather than independently
hardcoding Fast/Ultrafast exceptions.

### System-grounded feasibility findings

- `core/model_execution_options.py::validate_execution_options` currently validates
  supported and enabled ID collections together.
- `list_model_execution_option_definitions` currently passes all supported IDs as
  enabled IDs when validating a public definition list. Adding mutual exclusion
  without separating those operations would wrongly reject a catalog that
  supports both Fast and Ultrafast.
- The frontend currently toggles independent IDs in a set and renders independent
  switches/checkboxes. It must use the accepted exclusivity contract instead.
- The frontend request validator accepts only `fast`; the implemented option enum,
  schemas, generated clients, and readers must recognize Ultrafast in either path.
- Current prepared/inherited/Session snapshots already carry the enabled option
  collection. This is the reusable state boundary for Option A and the explicit
  conversion boundary for Option B.

### Accepted decision

The requester explicitly selected **Option A** on 2026-09-30 KST.

Keep the supported/enabled option ID collections as the canonical support and
preference representations. Add Ultrafast and a public code-owned exclusivity
relationship for the speed family. Server validation and composer presentation
use that same definition authority. Distinguish supported-option validation from
enabled-preference exclusivity, and preserve existing ordinary/Fast meanings and
profile/history formats.

Do not add a second authoritative speed field, provider-specific UI policy, broad
profile/history conversion, or an unrequested legacy fallback.

**Rejected alternative:** Option B. Its shape-level exclusivity does not justify
the broader API, state, history, and rollout conversion for this bounded feature.

**Consequences and risks:** collections remain capable of representing invalid
combinations until the shared server validation rejects them. Every explicit input,
profile preparation, inheritance, and provider-lowering boundary must enforce the
same registry-derived exclusivity. Existing prepared profiles remain authoritative
for the active attempt; subsequent retries retain the existing refresh rules.

## Current Behavior References

- [Model catalog and execution option authority](../spec/domain/model-catalog.md)
- [Inference-profile lifecycle](../spec/domain/agent.md)
- [Current premium processing and cost meaning](../spec/flow/chatgpt-oauth.md)
- [Delegated response-cost estimation](../spec/flow/agent-execution-loop.md)
- `python/apps/azents/src/azents/core/model_execution_options.py`
- `python/apps/azents/src/azents/core/inference_profile.py`
- `python/apps/azents/src/azents/engine/events/responses_lowering.py`
- `python/apps/azents/src/azents/engine/events/openai_responses.py`
- `typescript/apps/azents-web/src/features/chat/executionOptions.ts`
- `typescript/apps/azents-web/src/features/chat/containers/useChatInputContainer.ts`
- `typescript/apps/azents-web/src/features/chat/components/ChatInput.tsx`
- `typescript/apps/azents-web/src/trpc/routers/chat.ts`

## Implementation Boundary

The confirmed Requirements and accepted ADR-D1 authorize preparation of the
primary Design. Complete revision-bound Design approval is still required.
No implementation, dependency change, or Living Spec behavior update has been
requested.
