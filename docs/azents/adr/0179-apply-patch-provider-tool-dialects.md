---
title: "ADR-0179: Select Provider-Specific Tool Dialects for Apply-Patch"
created: 2026-07-21
tags: [architecture, backend, engine, llm, openai, runtime, tools]
---

# ADR-0179: Select Provider-Specific Tool Dialects for Apply-Patch

## Context

ADR-0172 introduced the model-visible `apply_patch` client tool as an ordinary JSON-schema function tool for OpenAI-developed GPT-family models. Its input carries an absolute Runtime `base_path` and one complete V4A document in the `patch` string. The Runtime Runner owns strict V4A parsing, path confinement, preflight, staging, optimistic revalidation, deterministic commit ordering, typed terminal results, and exact no-rollback partial-failure reporting.

Production use indicates that large V4A documents are a poor fit for JSON string arguments. The model must simultaneously produce valid V4A syntax and correctly escape every newline, quote, backslash, and control character inside a JSON object. OpenAI Responses custom tools support unconstrained plaintext input, so they can transport the same V4A document without JSON string escaping. The pinned OpenAI SDK also exposes typed custom-tool declarations, completed calls, call-input deltas, and call outputs.

Non-OpenAI providers do not share one verified custom-tool protocol. Many selected models do support ordinary JSON function calling, so removing the function representation would unnecessarily remove `apply_patch` from models that can generate V4A reliably enough through the established function contract.

The current Azents client-tool abstraction assumes one dialect:

- `FunctionToolSpec` always owns JSON Schema;
- `ToolCatalog.native_tools_for()` always emits `type=function`;
- `make_tool()` always parses handler input as JSON when an input model exists;
- canonical client calls retain `name` and `arguments` but not the provider call dialect;
- Responses output normalization recognizes only `function_call`;
- transcript lowering always reconstructs `function_call` and `function_call_output`; and
- continuation, orphan-output cleanup, streaming projections, and deterministic fixtures are function-call-specific.

A custom-tool declaration-only change would therefore make completed calls unknown to the normalizer and would reconstruct durable history with the wrong provider item types.

## Existing Decisions That Remain In Force

This ADR does not reopen ADR-0172 decisions about:

- strict V4A grammar and exact context matching;
- the absolute Runtime base-directory boundary;
- Add, Update, and Delete operations;
- path, file-kind, encoding, newline, and resource safety;
- Runner ownership of execution;
- preflight, staging, revalidation, and deterministic commit ordering;
- typed success and partial-failure results;
- no rollback after commit begins;
- commit-sensitive cancellation settlement;
- raw patch, source, and replacement content exclusion from logs; or
- coexistence with `edit`, `write`, `delete_file`, and process tools.

This ADR may supersede only ADR-0172-D1 and the model/tool-transport portions of ADR-0172-D14. Existing durable function-tool calls and results remain valid history.

## Goals

- Remove JSON string escaping from `apply_patch` input when the selected provider/model has a verified plaintext custom-tool protocol.
- Preserve ordinary JSON function-tool delivery as a preselected fallback for compatible non-OpenAI models.
- Keep one canonical `apply_patch` execution handler and one Runner `file.apply_patch` operation.
- Preserve the exact native call/output dialect required to replay a durable transcript safely.
- Make tool dialect selection deterministic before provider dispatch rather than retrying through a second dialect after a failed or ambiguous model call.
- Keep unsupported providers and models fail-closed.

## Non-Goals

- Using OpenAI's provider-native `type=apply_patch` operation protocol in this change.
- Translating a failed custom call into an inline function-tool retry.
- Changing Runtime patch grammar or filesystem semantics.
- Making every Azents client tool freeform.
- Treating an OpenAI-compatible endpoint or OpenAI-developed model identity alone as proof of custom-tool support.
- Persisting provider credentials, raw request frames, or raw patch content in new metadata.

## Decision

### ADR-0179-D1 — Use a generic plaintext custom tool on verified OpenAI Responses models

For a verified OpenAI Responses provider/model capability, expose the model-visible
`apply_patch` name as a generic `type=custom` tool with unconstrained plaintext input.
Normalize completed `custom_tool_call` items, return results through
`custom_tool_call_output`, and process `custom_tool_call_input` deltas only as ephemeral
transport state. Never execute a streaming fragment or an input whose completion was not
confirmed by the provider stream.

This choice removes JSON string escaping while preserving one complete strict V4A
document, one explicit absolute `base_path`, one visible client-tool call, and one
Runner-native `file.apply_patch` operation. The custom-tool input is a transport envelope;
the Runner remains the authoritative V4A parser and filesystem execution owner.

Do not adopt OpenAI's provider-native `type=apply_patch` protocol in this change. Its
individual create, update, and delete operation items do not preserve the existing V4A
batch, one-call Runner boundary, partial-failure reporting, and cancellation semantics
without a separate end-to-end protocol design. It may be reconsidered only through a
future ADR supported by model-quality evidence and an explicit Runtime transaction
decision.

The selected dialect is fixed before provider dispatch. A provider failure, malformed
call, cancellation, or ambiguous transport outcome never causes the same logical model
operation or tool execution to be resubmitted through another dialect.

### ADR-0179-D2 — Separate V4A semantic eligibility from provider tool transport

Resolve `apply_patch` exposure through independent fail-closed capability dimensions:

1. the selected model has reviewed V4A `apply_patch` semantic eligibility;
2. the actual provider/model route has verified OpenAI custom plaintext transport; and
3. the actual provider/model route has verified ordinary JSON function transport.

An eligible model uses the custom dialect when dimension 2 is verified. Otherwise, it
uses the JSON function dialect when dimension 3 is verified. When semantic eligibility
or both usable transports are denied or unknown, do not expose `apply_patch`.

Function-calling support alone is not V4A eligibility. It proves only that a route can
carry a JSON tool call; it does not establish strict V4A generation, source preservation,
multi-file coherence, or correct base-path selection. Initial semantic eligibility
preserves the implemented ADR-0172 GPT-family compatibility behavior without widening it
to other developers or arbitrary function-calling models. Future non-GPT eligibility
requires an explicit reviewed compatibility rule backed by repeatable conformance
evidence.

Consequently, initial "non-OpenAI fallback" means a non-OpenAI provider route carrying a
semantically eligible OpenAI-developed GPT model through independently verified JSON
function transport. It does not make `apply_patch` available to Anthropic-, Google-, xAI-,
or other developer models merely because their routes support function calling. Those
models require their own V4A semantic conformance approval before either dialect is
available.

Transport support is route-specific. Official OpenAI identity, an OpenAI-compatible API
shape, an OpenAI-developed display name, or a provider catalog's generic function flag is
not sufficient by itself. Aliases, opaque routing pools, provider failover sets, and
unknown model snapshots are eligible only when every possible routed target satisfies the
same semantic and transport contract; otherwise the result is unknown and therefore
unavailable.

Capability resolution and dialect selection occur before the prepared request is built.
One request exposes exactly one logical `apply_patch` declaration. Capability changes on
a later turn affect only new declarations; they do not reinterpret a previously admitted
call or change the dialect used to lower its result.

### ADR-0179-D3 — Persist the originating wire dialect on both call and result

Add a closed canonical `wire_dialect` discriminator to both `ClientToolCallPayload` and
`ClientToolResultPayload`:

- `json_function`
- `plaintext_custom`

Retain the physical `arguments: str` field, but redefine it as the exact decoded raw
client-tool input string. For `json_function`, it contains the provider's JSON argument
string. For `plaintext_custom`, it contains the provider's plaintext custom-tool input.
Consumers branch on `wire_dialect` before interpreting the field. They do not infer the
dialect from the tool name, JSON parseability, V4A markers, current model capability, or
the opaque native artifact.

The call is authoritative. Result creation copies the call's dialect, and callers cannot
select a result dialect independently. When both events are available, a mismatch is
durable-state corruption and fails closed rather than relabeling either event. Execution
identity remains the canonical `call_id`; changing the dialect cannot authorize a second
execution.

Existing records written before `wire_dialect` have one explicit compatibility
interpretation at persistent canonical deserialization: a missing field means
`json_function`. Apply that upgrade at every database JSON read boundary, including Event
transcript repositories, legacy chat/message projections, and AgentRun active-call state.
Do not express it as a general Pydantic field default that also permits new in-process
writers to omit the field. Newly written calls and results always persist an explicit
value. Explicit null, unknown, or malformed values do not receive the legacy
interpretation and are not executed or lowered as another dialect.

Same-compatible native artifacts may replay the exact provider item only when the native
compatibility key matches adapter, native format, provider, model, and schema version.
Native artifact content remains opaque and subordinate to canonical dialect state.
Compatible canonical reconstruction uses the stored decoded input string without
trimming, Unicode normalization, newline translation, JSON reserialization, or V4A
regeneration.

Distinguish active protocol continuation from completed historical context:

- A result that still must be delivered as part of the originating tool continuation is
  lowered with its stored dialect and original `call_id` through a verified compatible
  route. An incompatible route fails closed; it does not relabel or text-project the
  pending continuation. Persistence of both call and result does not by itself make the
  pair historical; the result remains pending until a successful later model boundary has
  consumed it.
- A durably completed historical call/result pair may become bounded, explicitly labeled
  readable context when a later target cannot represent the stored dialect. This
  projection is non-executable, never creates an active call, never presents a truncated
  V4A document as complete, and does not modify the durable events. The later target may
  be selected in the same AgentRun after turn-boundary profile rebuilding or in a later
  AgentRun.

### ADR-0179-D4 — Use one exact base-path header before an unchanged V4A body

The plaintext custom-tool input has exactly this shape:

```text
*** Base Path: /absolute/runtime/path
*** Begin Patch
...
*** End Patch
```

The Engine locates the first ASCII LF. The substring before it must be the exact ASCII
prefix `*** Base Path: ` followed by one non-empty bounded Runtime path. The substring
after it must begin immediately with `*** Begin Patch`; no blank line, Markdown fence,
commentary, BOM, or other prefix is allowed.

The base-path header uses exact case and punctuation, exactly one ASCII space after the
colon, and LF rather than CRLF. The path must be syntactically absolute for the current
Runtime platform and contain no NUL, CR, LF, tab, prohibited C0/C1 control, U+0085,
U+2028, or U+2029 character. The envelope parser does not trim, Unicode-normalize,
canonicalize, resolve, or otherwise replace the extracted path. Runtime Runner remains
authoritative for existence, directory kind, symlink behavior, confinement, and
filesystem semantics. Runtime roots that require prohibited header characters are not
representable through the plaintext dialect.

The patch is exactly the decoded provider string slice after the first LF. Streaming
deltas are concatenated in provider sequence order. The Engine does not strip, split and
rejoin lines, translate newlines, normalize Unicode, remove fences, append a final
newline, JSON-round-trip, or reconstruct V4A operations. It verifies only the immediate
start marker and leaves the complete V4A grammar, end marker, trailing-input, path,
context, and mutation validation to Runner. Header-like text inside the V4A body is
ordinary patch content and is not scanned as a duplicate preamble.

Bound total custom input, header, and UTF-8 path bytes cumulatively while receiving
deltas. An incomplete, oversized, or malformed envelope invokes Runner zero times and
returns a stable safe category without echoing the rejected path or input. It never
triggers JSON-dialect retry.

Declare the initial OpenAI custom tool with unconstrained `format.type=text`. Do not add
a provider grammar in the initial cutover. A future grammar requires model evaluation
showing material adherence improvement, acceptance of every Runner-valid V4A document
and arbitrary patch content, consistent behavior across every eligible model, and no
change to replay semantics. Grammar adoption is a versioned compatibility-profile change,
not execution authorization.

### ADR-0179-D5 — Initially enable custom input only on reviewed official OpenAI API routes

Initial plaintext-custom selection requires the complete conjunction of:

- `LLMProvider.OPENAI` with API-key authentication;
- the OpenAI-native Responses adapter;
- the canonical official OpenAI API endpoint with no custom or environment-derived base
  URL override;
- a reviewed V4A semantic profile resolved for the selected model snapshot;
- an exact reviewed custom-tool transport profile; and
- an enabled disable-only rollout gate.

The initial custom transport profile enumerates reviewed exact model identifiers,
preferably immutable snapshots where available. Open-ended GPT-name, developer, family,
function-calling, or lowerer-class predicates do not grant custom capability. A rolling
alias, fine-tune, deployment name, routing pool, or unresolved target requires its own
profile and is unknown until every possible routed target and rollback condition are
verified.

Do not enable plaintext custom for ChatGPT OAuth, OpenRouter, Azure, enterprise gateways,
reverse proxies, custom base URLs, or other OpenAI-compatible endpoints in the initial
cutover. Shared SDK or lowerer code does not prove a shared provider contract. A route may
be promoted later only after its own deterministic request, stream, completion, output,
continuation, cancellation, persistence, replay, and bounded live conformance evidence
passes. Promotion uses a reviewed code-owned positive rule.

An unverified custom route may still receive the JSON function dialect when V4A semantic
eligibility and its function transport are independently verified. Custom denial never
implies that function fallback is safe, and provider rejection never dynamically grants
or probes another dialect.

The positive allowlist is code-owned. Runtime or administrator configuration cannot force
custom input onto an unreviewed model or endpoint. Operations may provide a global or
profile-specific kill switch that only reduces new custom exposure. Disabling exposure
affects new prepared calls only; it does not relabel durable custom events or abandon an
active custom continuation. Deployments must retain custom event parsing and lowering
support after any custom record can be written.

Profile approval evidence records the model identifier, route and endpoint class,
adapter version, fixture suite, live verification date and sample size, malformed-envelope
rate, continuation success rate, and approver. Required live cases use disposable Runtime
roots and cover update, create/delete, multi-file V4A, Unicode and newline preservation,
long content, malformed envelopes, result continuation, and safe cancellation boundaries.

### ADR-0179-D6 — Expand full lifecycle compatibility before any production custom write

Deliver the change through compatibility-first production phases. Phase boundaries are
deployment-safety boundaries and need not map one-to-one to pull requests.

1. Expand canonical call/result payloads and every serializer/consumer to accept missing
   legacy dialect and explicit `json_function`, while all model requests remain function-
   only. If an older consumer rejects additive fields, deploy tolerant readers before new
   writers emit explicit JSON dialect.
2. Deploy dormant end-to-end `plaintext_custom` lifecycle support: declaration lowering,
   stream and completed-call normalization, persistence, envelope execution, result
   persistence, custom output lowering, continuation, restart recovery, cancellation,
   compaction, export, API/WebSocket projection, frontend presentation, and redaction.
   Shared production traffic still cannot select custom input.
3. Deploy exact profiles, official-endpoint checks, stable cohort selection, safe metrics,
   disable-only gates, deterministic E2E, and live-evaluation tooling with positive
   production exposure off.
4. Enable bounded cohorts only after every process that may receive, execute, recover,
   compact, display, export, or continue the event is at the full lifecycle compatibility
   floor; old leased, delayed, retried, dead-lettered, and long-lived work is drained or
   proven reclaimable only by upgraded consumers.

No shared production state contains `plaintext_custom` before phase 4. Isolated test and
canary environments may exercise custom input only when their complete processing path is
already compatible and their Runtime roots are disposable.

From the first production custom write onward, full custom lifecycle support is a
permanent minimum deployment version. Operational rollback disables new custom selection
and allows verified JSON function selection for new eligible calls while continuing to
execute, recover, display, and continue existing custom events. It never deploys a binary
that merely deserializes custom state but cannot complete its lifecycle, and it never
relabels or re-executes an existing call.

The selection predicate is conjunctive and pre-dispatch: reviewed semantic profile,
reviewed route/model custom profile, official endpoint, positive code-owned eligibility,
enabled disable-only gate, and stable cohort membership. Missing, malformed, or
inconsistent configuration disables custom exposure. Cohort assignment is deterministic
for a stable conversation or tenant key and is observable without logging model input.

## Compatibility Constraints

- One prepared model request exposes exactly one `apply_patch` dialect under the name `apply_patch`.
- Initial non-OpenAI function fallback remains limited to semantically eligible
  OpenAI-developed GPT models on routes with an independently verified function
  transport profile.
- A provider failure never triggers automatic resubmission through another dialect.
- A durable call is executed at most once under the existing call identity and foreground-tool ownership contract.
- Function and custom calls must lower back to their matching provider call/output item pairs.
- Model switches and provider switches must lower older calls through a safe canonical representation or an exact compatible native artifact; they must not relabel old custom calls as function calls or vice versa.
- Tool Search, declaration budgeting, prompt projection, execution lookup, cancellation, active-tool projection, compaction, context inspection, and frontend rendering continue to use one prepared Tool Catalog snapshot.

## Consequences

### Positive

- OpenAI models can produce one V4A document without JSON string escaping.
- The validated Runner transaction, path-safety, cancellation, and partial-failure
  contract remains unchanged.
- V4A semantic quality and provider transport support become independent reviewed
  capabilities.
- Eligible non-custom routes retain the existing JSON function representation without a
  runtime retry or duplicate-execution path.
- Durable calls remain interpretable after model, provider, profile, or rollout changes.
- Compatibility-first deployment prevents a custom writer from outrunning execution,
  recovery, continuation, UI, or export consumers.

### Negative

- Canonical client-tool events, results, active state, adapters, compaction, UI, and tests
  all become dialect-aware.
- The plaintext envelope intentionally cannot represent Runtime roots containing control
  or line-separator characters.
- Initial custom coverage excludes ChatGPT OAuth and compatible endpoints even when they
  may work empirically.
- Exact model profiles and conformance evidence require ongoing maintenance as provider
  models and aliases change.
- Once production custom events exist, dual-dialect lifecycle support cannot be removed
  through an ordinary code rollback.
- Completed custom history may require a lossy bounded text projection on an incompatible
  future provider instead of structured tool replay.

## Alternatives Considered

- Keep the current JSON function tool everywhere. Rejected because it preserves the
  double-grammar JSON escaping failure that motivated this change.
- Use a generic OpenAI plaintext custom tool with JSON function fallback elsewhere.
  Selected, subject to the semantic and route-transport gates in this ADR.
- Use OpenAI's provider-native apply-patch tool with a Runner adapter. Deferred because it
  does not preserve the existing one-call V4A batch and Runner transaction contract.
- Introduce provider-neutral custom/freeform transport for every client tool immediately.
  Rejected as unnecessary scope; the internal abstraction becomes variant-capable, while
  production plaintext exposure remains limited to `apply_patch`.
- Remove `base_path` from model input and infer it from Runtime or Project state. Rejected
  because it weakens the explicit execution boundary and is ambiguous for multi-root
  sessions.
