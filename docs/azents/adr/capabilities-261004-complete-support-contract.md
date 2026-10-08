---
title: "Complete Model Capability Support Decisions"
created: 2026-10-04
tags: [backend, engine, model-catalog, reliability]
document_role: primary
document_type: adr
snapshot_id: capabilities-261004
---

# Complete Model Capability Support Decisions

## Authority

The requester explicitly replaced the symptom-only repair with the complete correction in [capabilities-261004/REQ](../requirements/capabilities-261004-complete-support-contract.md). This snapshot records only confirmed outcomes and implementation boundaries derived from those outcomes. Historical adopted decisions remain unchanged; their unknown-state final-support policy is superseded only within the boundary below.

### capabilities-261004/ADR-D1. Definitive supported-feature authority

**Accepted:** 2026-10-04, explicitly directed by the requester.

**Authority:** `capabilities-261004/REQ-1`, `REQ-3`, and `REQ-4`.

Use one definitive supported-feature interpretation for publication, selection, presentation, configuration and requests. A feature included in the supported set is supported; an omitted feature is not supported. Unknown/unverified final-capability states and the competing conservative boolean interpretation are removed as authority.

Original declaration absence/null, source coverage, exact account/model/route scope, and factual-versus-codec exclusions remain evidence and diagnostics, not a third final support state. Support must be established by applicable declarations or verified producer/route contracts before inclusion. An omitted listing field is not proof of denial when the applicable contract already establishes support. This decision does not authorize blanket positive defaults from an SDK, model-name pattern, or another host.

Conditional request constraints remain real constraints on supported features; they do not create an unknown feature. Configuration potential and actual request admissibility must be distinct evaluations of that same supported set.

**Rejected alternatives**

- Add an unverified badge while keeping supported models unknown: rejected by the requester.
- Permit unknown requests but leave published support incorrect: repairs a symptom without correcting the required authoritative values.
- Change every unknown feature to true: invents facts and enables unrelated unsupported controls.

**Required evidence**

- Actual researched model declarations and contract-derived feature values agree with the published supported set.
- No consumer uses a second conservative support view as independent authority.
- Missing information remains diagnosable without appearing as an unknown supported-feature state.

### capabilities-261004/ADR-D2. Replace the inconsistent transformation and request-admission units

**Accepted scope:** 2026-10-04, requester explicitly required implementation reconsideration and replacement when necessary.

**Authority:** `capabilities-261004/REQ-2`, `REQ-3`, and `REQ-4`.

Replace the units that mix producer facts, route representability, display projection and actual request validation. Decode producer declarations once, compile final support and constraints once, and normalize effective provider request intent once before applying the shared admission rule. Internal text/title/compaction/memory operations must not bypass that boundary.

SDK wire encoding and model facts are different responsibilities. Neither author-intent settings ignored by the SDK nor captured defaults overwritten by explicit native reasoning may satisfy a request condition. Budget/adaptive/disabled reasoning forms retain their actual meaning rather than being converted to an invented effort level.

Existing account-visible inventory, exact model identities, authorization, ownership, ordered quota fallback, source publication and immutable historical provenance remain outside this replacement authority. No new credential acquisition, alternate model, runtime source fetch, automatic user-setting mutation or production write is authorized by this decision.

**Rejected alternatives**

- Continue adding local boolean exceptions to each consumer: recreates divergent admission rules.
- Treat the SDK's generic profile as model knowledge: codec traits do not establish provider/model support.
- Validate only foreground lowering: internal helper requests then remain unchecked.

**Required evidence**

- Cross-provider tests use the actual SDK request shape and body-override precedence.
- Google and Bedrock explicit thinking settings cannot inherit an incompatible saved effort for predicate evaluation.
- Internal generated output tools and structured-response fields are included in actual request intent.

### capabilities-261004/ADR-D3. Real-model evidence is an independent completion gate

**Accepted:** 2026-10-04, explicitly directed by the requester.

**Authority:** `capabilities-261004/REQ-5`.

Keep researched expected values separate from implementation-generated values. Verify original official/account declarations, compiled capabilities, selected values, display interpretation and actual requests. Distinguish source evidence, SDK serialization, and provider acceptance. Unavailable account/route checks remain explicitly incomplete.

No live catalog refresh, choice update, restart, merge or deployment follows automatically from a diagnostic or a passing test.

**Rejected alternatives**

- Infer correctness from unit tests constructed from the implementation's own defaults.
- Count a synthetic serializer success as successful provider execution.
- Declare unsupported credentials/routes verified by omission.

## Open Implementation Mechanisms

The exact public field organization, safe handling of existing stored descriptors, and replacement interfaces are being validated against the repository. Those mechanisms must preserve the accepted scope; this ADR does not grant unapproved migration, active-operation replacement, or automatic saved-selection policy changes.

### capabilities-261004/ADR-D4. Retain the existing canonical reasoning domain

**Accepted:** 2026-10-04, explicitly directed by the requester.

**Authority:** `capabilities-261004/REQ-6`.

The pre-Pydantic implementation retained the original provider preset array while excluding noncanonical `ultra` from selectable efforts. Its parser attempted the seven-value `ModelReasoningEffort` enum and omitted values outside that domain. Its fixture supplied `ultra` and explicitly expected only low, medium, high, xhigh and max. Preserve that behavior, without adding an alias or direct wire extension.

The provider's description associates ultra with automatic task delegation. The official Codex implementation separately resolves the local ultra selection into a model-owned ordinary effort and proactive multi-agent mode. This compound client behavior is not a new generic reasoning control authorized by this repair.

**Rejected alternatives**

- Add `ultra` to the product enum and pass it directly to the SDK: changes the required pre-cutover behavior.
- Map every ultra declaration to max: invents a normalization that the existing Azents parser did not perform.

**Required evidence**

- The pre-cutover parent of `f4c696449` and its ChatGPT listing fixture match the repaired normalized effort list.
- Raw ultra evidence remains available for diagnostics while public selectable values and actual request validation retain the canonical domain.
