---
title: "Reliable Automatic Session Titles Design"
created: 2026-08-03
updated: 2026-08-03
tags: [session, title, llm, external-channel, backend, testenv]
document_role: primary
document_type: design
snapshot_id: title-260803
---

# Reliable Automatic Session Titles Design

- Snapshot: `title-260803`
- Document reference: `title-260803/DESIGN`
- Requirements: [`title-260803/REQ`](../requirements/title-260803-reliable-automatic-title.md)
- Decisions: [`title-260803/ADR`](../adr/title-260803-reliable-automatic-title.md)
- Mode: Collaborative
- Decision owner: requester

## Current Behavior and Gap

`SessionTitleService` loads the Agent's saved lightweight `AgentModelSelection`, resolves its integration credentials, and calls `generate_session_title_with_model`. Every provider currently receives a plain-text Responses request. OpenAI and ChatGPT OAuth use the official OpenAI SDK helper; other providers use the shared LiteLLM Responses helper. The model output is reduced to the first non-empty line by `clean_generated_title` and may replace only the matching `auto_initial` title.

The saved model selection already contains tri-state `normalized_capabilities.tool_calling.strict_json_schema`, but title generation does not read it. Both shared Responses helpers already accept a typed `text` configuration, and the pinned OpenAI SDK validates a minimal `json_schema` text format. The common provider-failure taxonomy retains category, status, code, and type, but not the provider error parameter needed to distinguish a rejected output-format field from unrelated invalid requests.

The current prompt mixes semantic title guidance with a plain-text-only output instruction. It also prohibits `summary` while an example requires that word, describes the source as an "initial user prompt," and prohibits all tool names even when the user explicitly names a tool. External Channel invocation markup remains in the source body; the confirmed scope handles it through prompt guidance only.

## Requirement and Decision Traceability

| Requirements | Decisions | Mechanism |
| --- | --- | --- |
| REQ-1, REQ-2 | D1 | M1 capability-directed title invocation mode |
| REQ-1, REQ-2 | D2 | M2 operation-local Structured Output compatibility transition |
| REQ-2, REQ-3 | D1, D2 | M3 shared title contract, mode-specific instructions, and decoding |
| REQ-3 | — | M4 coherent prompt-only request interpretation |
| REQ-2, REQ-4 | D1, D2 | M5 unchanged automatic-title authority and projection lifecycle |

## Architecture and Ownership

The Agent's saved lightweight `AgentModelSelection` remains the source of truth for provider integration, model identifier, and normalized capability. The live model catalog is not consulted during title generation.

`SessionTitleService` owns one operation-local title mode state machine. The shared Responses helpers remain responsible for provider transport and typed request validation. The common provider-failure contract retains bounded typed fields needed by the title service to recognize explicit output-contract incompatibility. The existing Session title columns remain the only durable title source of truth.

No model-selection policy, catalog migration, database schema, public API, frontend setting, invocation-reference state, queue, outbox, reconciliation process, or deployment unit is added.

## M1. Capability-Directed Title Invocation Mode

After loading the Agent, `SessionTitleService` reads the effective lightweight selection's saved `normalized_capabilities.tool_calling.strict_json_schema` value once for the title operation.

The initial mode is selected as follows:

| Saved capability | Initial mode | Compatibility transition |
| --- | --- | --- |
| `true` | Structured Output | Never |
| `false` | Plain text | Never |
| `null` | Structured Output | M2 may transition once to plain text |

Every physical request uses the same saved provider integration ID, runtime model, credentials, title source Event, watchdog policy, and Session ownership fence. Catalog refreshes cannot change an operation or existing Agent snapshot.

## M2. Operation-Local Compatibility Transition

The title operation carries an in-memory active mode and a boolean indicating whether the unknown-capability compatibility transition has occurred. This state is not persisted and does not survive process interruption.

For an unknown capability, Structured Output transitions once to plain text only after one of these observations:

1. a classified provider failure identifies the rejected parameter or provider code as the response-format or JSON Schema contract;
2. an OpenRouter Structured Output request reports that no routed endpoint accepts all requested parameters; or
3. a nominally successful response cannot be decoded through the title schema.

The common `ModelProviderFailure` contract is extended with a sanitized nullable provider error parameter. OpenAI SDK and LiteLLM mappings populate it from typed provider error bodies when present. A title-scoped classifier matches only bounded parameter paths and provider codes associated with the Structured Output request. It does not use unrestricted provider-message substring matching and does not treat the broad `INVALID_REQUEST` category alone as incompatibility.

Authentication, permission, billing, rate limit, model unavailable, context limit, content policy, timeout, cancellation, transport, provider unavailable, and unclassified failures retain the current failure path and do not change modes.

The compatibility transition does not consume the existing transient provider retry budget. Once it occurs, all remaining attempts in that operation use plain text. Existing retry backoff and title-ownership revalidation continue in the active mode and cannot cause a second mode transition. Process interruption retains no probe result; a later independently authorized title operation does not exist under the current title lifecycle.

For an OpenRouter Structured Output request, the operation supplies provider routing metadata requiring support for all requested parameters. This makes unsupported endpoint routing observable instead of allowing a provider to silently ignore the schema request. It is applied only to the Structured Output title call and does not alter the Agent's ordinary model requests. Plain-text mode uses the existing routing behavior.

ChatGPT OAuth remains unknown unless its own catalog projection later supplies verified capability. It uses the same official SDK request shape against the existing ChatGPT OAuth backend. Explicit contract rejection or schema-decode failure may transition the operation to plain text; public OpenAI catalog capability is never copied into the ChatGPT OAuth snapshot.

## M3. Shared Title Contract and Mode-Specific Decoding

A provider-compatible minimal schema defines exactly one required string field:

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string"
    }
  },
  "required": ["title"],
  "additionalProperties": false
}
```

The schema deliberately omits provider-sensitive semantic constraints and length keywords. Existing application normalization remains responsible for whitespace, non-empty output, and the 50-character title bound.

Structured Output calls pass this schema through the existing Responses `text` configuration with strict mode enabled. The response text is decoded into a closed one-field title value. Syntax failure, a missing field, a non-string value, or additional fields is a schema-decode failure. For unknown capability it invokes M2; for explicit support it ends title generation without a plain-text transition.

Plain-text mode uses the existing response extraction and `clean_generated_title` behavior. No semantic validator, prohibited-prefix list, echo detector, language detector, or provider-reference parser is introduced.

Structured and plain requests share the same semantic title instructions. Only plain mode appends an output instruction requiring title-only plain text without JSON, labels, quotes, or explanation. Structured mode relies on its schema for the response envelope.

## M4. Coherent Prompt-Only Request Interpretation

The shared semantic prompt keeps the current title purpose, same-language rule, examples, one-line expectation, 50-character bound, preservation of important request terms, and prohibition on answering the user's request.

It changes only these established defects and scope items:

- remove `summary` and related legitimate task wording from the blanket prohibited-term rule;
- replace the `Generate a title for this initial user prompt` wrapper with direct wording that asks for a title from the request;
- preserve products, tools, filenames, and technical terms explicitly named by the user while prohibiting invention of internal Agent actions or tools; and
- instruct the model to ignore platform markup used only to address the Agent, such as Bot or App mentions, while preserving references relevant to the request.

The canonical External Channel body, reference mappings, deterministic `auto_initial` title input, Event payload, and normal Agent-visible transcript remain unchanged. No guarantee is claimed that every model follows the invocation-markup instruction, consistent with the exclusion of semantic validation and deterministic mention removal.

## M5. Existing Title Authority and Projection Lifecycle

`SessionTitleService` continues to commit only a successful normalized title while the Session still has the matching `auto_initial` source and exact generation Event. Manual title changes and clears remain authoritative.

The Structured-to-plain compatibility transition occurs entirely before a successful title commit. At most one `auto_generated` commit can win, and only that commit may invoke the existing post-commit External Channel thread-title projection. Mode transitions and failed attempts do not create another projection trigger.

Title generation remains operation-scoped best effort. Failure, timeout, exhaustion, cancellation, or process interruption preserves the deterministic title and never gates Session creation, admission, wake, AgentRun creation, Agent output, or ordinary provider delivery.

## Internal Interfaces and Data

### Title invocation mode

An internal closed mode distinguishes `structured` and `plain_text`. The tri-state capability selects its initial value. No public enum or persisted field is added.

### Structured title value

A closed internal decoder accepts only an object containing the required string `title`. It returns the string to the existing normalization boundary. The decoded object is not persisted.

### Provider failure parameter

The internal `ModelProviderFailure` gains a sanitized nullable provider error parameter beside the existing code and type. All provider mappings pass a value explicitly, using `None` when unavailable. This remains internal diagnostic and control data and is not exposed through a product API or stored in title state.

### OpenRouter routing metadata

The shared LiteLLM Responses helper accepts explicit operation-scoped request metadata so the Structured Output title call can send `provider.require_parameters=true`. Callers that do not need provider routing pass no metadata. The helper continues to own endpoint and credential normalization.

## Failure, Retry, and Recovery

| Outcome | Active behavior |
| --- | --- |
| Explicit support, Structured success | Decode and normalize title |
| Explicit support, contract rejection or decode failure | End generation; preserve `auto_initial` |
| Explicit non-support | Use plain text under current retry policy |
| Unknown, Structured success | Decode and normalize title |
| Unknown, explicit contract incompatibility | Transition once to plain text |
| Unknown, schema-decode failure | Transition once to plain text |
| Any capability, authentication/permission/billing failure | Existing terminal provider-failure behavior |
| Any capability, rate limit/transport/provider unavailable | Existing retry policy in the active mode |
| Timeout or cancellation | Preserve `auto_initial`; no mode transition |
| Plain-text failure or exhaustion | Preserve `auto_initial` |

No compatibility result or probe is persisted. No recovery scan, backfill, retry queue, reconciliation, or second title trigger is added.

## Security and Privacy

The schema and prompt add no new user or provider data. Provider error parameters are sanitized through a bounded identifier/path format before entering the common failure object or logs. Raw provider response bodies, credentials, title input, model output, and External Channel content remain excluded from logs.

Prompt-only mention handling does not modify canonical provider evidence or normal Agent context. It also does not claim a security boundary: user content remains untrusted source material, and Structured Output constrains response shape rather than semantic correctness.

## Observability

Existing title provider-attempt logs gain bounded fields for:

- saved Structured Output capability state;
- active title output mode;
- whether an operation-local compatibility transition occurred; and
- sanitized output-contract incompatibility kind.

Logs do not include schema content, title input, decoded title, raw model output, provider message body, or invocation markup. Existing provider category, code, type, fingerprint, attempt number, and retry outcome remain available.

## Migration, Rollout, and Rollback

No database migration or backfill is required. Existing Agent and Workspace snapshots already deserialize missing `strict_json_schema` as `null`, so they enter the unknown branch. Explicit `true` and `false` snapshots follow their corresponding branches immediately after deployment.

Rollout changes only future automatic-title calls. Existing Session titles and title-generation ownership remain unchanged. Rollback restores plain-text-only generation; the added nullable internal failure field and operation-local helper interfaces leave no durable state to clean up.

## Test Strategy

### Deterministic E2E matrix

The credential-free model/provider fake is extended to observe title request mode, schema, prompt, and OpenRouter routing metadata and to return controlled success or typed failure outcomes.

The primary E2E matrix covers:

- `true`: one Structured request, successful title commit, zero plain requests;
- `true`: schema-decode failure, no plain request, deterministic title retained;
- `false`: one plain request and zero Structured requests;
- `null`: Structured success and zero plain requests;
- `null`: explicit unsupported-format failure followed by plain success using the same model;
- `null`: no-compatible-OpenRouter-endpoint failure followed by plain success with Structured-only `require_parameters=true`;
- `null`: schema-decode failure followed by plain success;
- `null`: authentication, rate limit, timeout, cancellation, transport, and provider-unavailable outcomes that do not switch modes;
- transient retry after mode transition remaining in plain mode;
- manual title change between attempts preventing a later commit;
- successful title commit retaining the existing single Discord projection trigger; and
- External Channel invocation markup present in the source while the prompt contains the ignore-markup instruction and no new invocation-reference state exists.

### Focused unit and integration coverage

- tri-state mode selection from saved `AgentModelSelection` snapshots;
- minimal schema validation through the pinned OpenAI SDK type;
- Structured response decoding and plain cleanup separation;
- provider error parameter sanitization and mapping for OpenAI and LiteLLM;
- narrow title-contract incompatibility classification without broad 400 matching;
- ChatGPT OAuth unknown-capability success, explicit rejection, ignored-schema decode failure, and non-fallback operational failures;
- OpenRouter request metadata applied only to Structured title calls;
- prompt contradiction removal, direct request wrapper, user-mentioned tool preservation, and prompt-only invocation-markup guidance; and
- absence of model switching, catalog re-resolution, semantic validation, canonical-body mutation, persistence, or additional projection triggers.

The deterministic E2E lane remains CI authority. No live provider or ChatGPT OAuth credential is required; an optional live diagnostic may be run manually but cannot replace deterministic acceptance evidence.

## Feasibility

| Area | Result | Evidence and condition |
| --- | --- | --- |
| Tri-state selection | Feasible | Saved `AgentModelSelection.normalized_capabilities.tool_calling.strict_json_schema` is available before title invocation. |
| Structured request | Feasible | Both title transport paths already accept typed Responses `text` configuration; the pinned SDK validates the minimal strict schema. |
| Structured decoding | Feasible | Existing response extraction returns bounded text that can be decoded through one closed internal schema before current title normalization. |
| Unknown-mode transition | Feasible | `SessionTitleService` already owns attempt/retry state and title-authority revalidation; an operation-local active mode adds no persistence. |
| Explicit incompatibility evidence | Conditional | OpenAI and LiteLLM mappings can retain typed error parameter/code fields. Providers that expose neither typed rejection nor an undecodable success cannot trigger fallback from an ambiguous failure. |
| ChatGPT OAuth | Conditional but safe | The official SDK accepts the request shape and the backend uses the existing Responses path. The capability remains unknown; explicit rejection or decode failure falls back, while ambiguous failures preserve `auto_initial`. |
| OpenRouter routing | Feasible | LiteLLM Responses accepts operation-scoped extra request body metadata; the title helper can require supported parameters only for Structured calls. |
| Prompt changes | Feasible | One shared top-level title prompt and one request wrapper own the current behavior. |
| Existing authority and projection | Feasible | Current repository replacement fence and post-commit projection remain downstream of one successful generated title. |

No feasibility blocker remains. Conditional provider evidence degrades safely to the deterministic initial title rather than widening fallback or blocking execution.

## Alternatives Rejected by Requirements or ADR

- A dedicated or fallback model would violate same-model ownership.
- Global lightweight-model restriction would couple unrelated lightweight work to title formatting and exclude unknown compatible models.
- Always trying Structured Output would disregard explicit non-support.
- Falling back after explicit-support failures would disregard the saved tri-state policy.
- Falling back on every provider failure would conflate operational incidents with format incompatibility.
- Semantic validators, prohibited-prefix lists, and deterministic invocation-reference removal are outside confirmed scope.

## Design Authority

- Design revision: `1`

| ID | Material design mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Saved tri-state model capability selects the operation's initial title output mode without catalog re-resolution or model switching | REQ-1, REQ-2, ADR-D1 | `decided` |
| M2 | Unknown capability may transition once to plain text only on bounded output-contract rejection, routing, or decode evidence while retaining current retry behavior | REQ-1, REQ-2, ADR-D2 | `decided` |
| M3 | Minimal strict one-field title schema and mode-specific decoding share the same semantic prompt and existing normalization boundary | REQ-1, REQ-2, REQ-3, ADR-D1, ADR-D2 | `derived` |
| M4 | Prompt fixes contradictions and meta framing and handles invocation markup only through instruction, without semantic validation or canonical input mutation | REQ-3 | `required` |
| M5 | Existing title ownership, failure isolation, retry lifecycle, and single post-commit projection trigger remain unchanged | REQ-2, REQ-4; conversation and agent-execution-loop Specs | `existing` |

## Removal and Replacement

| Existing unit or behavior | Removal authority | Replacement or remaining authority | Removal boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Plain-text-only automatic title invocation | REQ-1, ADR-D1, ADR-D2 | M1 tri-state mode and M2 bounded transition | `SessionTitleService` and title model helper | Tri-state E2E matrix proves exact request counts and unchanged model identity |
| One prompt combining semantic and plain-text envelope instructions | REQ-3 | M3 shared semantic instructions plus mode-owned envelope | Title prompt and request construction | Request-capture tests compare Structured and plain prompt surfaces |
| Contradictory `summary` prohibition, meta `user prompt` wrapper, and overbroad tool-name prohibition | REQ-3 | M4 coherent prompt wording | Title prompt constant and input wrapper | Focused prompt assertions and fake-model request evidence |
| Broad invalid-request inference as a potential fallback signal | REQ-1, REQ-2, ADR-D2 | M2 typed parameter/code/decode evidence only | Provider failure mapping and title classifier | Negative tests prove unrelated 400/auth/rate/timeout/5xx outcomes do not switch modes |
| Invocation-reference persistence or canonical message rewriting | Explicit REQ non-goal | None; M4 prompt-only handling | No Event, mailbox, canonical message, or DB field is added | Diff/schema tests and External Channel payload snapshots remain unchanged |

## Design Approval

- Mode: `Collaborative`
- Decision owner: requester
- Approved on: `2026-08-03`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5`
- Approved scope: capability-directed same-model Structured Output and plain-text title invocation, one bounded unknown-capability output-mode transition, a minimal strict title schema, coherent prompt-only invocation-markup handling, and unchanged automatic-title authority and projection lifecycle.
