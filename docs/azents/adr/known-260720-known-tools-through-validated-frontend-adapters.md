---
title: "Render Known Tools Through Validated Frontend Adapters"
created: 2026-07-20
tags: [architecture, frontend, chat, tools, ux, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: known-260720
historical_reconstruction: true
migration_source: "docs/azents/adr/0176-render-known-tools-through-validated-frontend-adapters.md"
---

# known-260720/ADR: Render Known Tools Through Validated Frontend Adapters

## Context

[group-260720/ADR](./group-260720-group-chat-activity-in-the-frontend.md) established Generic tool rendering as the permanent compatibility boundary and allowed specialized presentation only for registered tool identities whose payloads validate. [ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-194) retained that boundary while deferring individual tool detail designs.

The current web implementation still renders every client tool through `ToolCallCard` and every provider-hosted tool through `ProviderToolCallCard`. These components expose raw arguments, raw textual output, status, and attachments, but they cannot communicate common operations such as file reads, searches, edits, shell commands, memory actions, or subagent lifecycle in a concise product-level form.

This follow-up must add useful known-tool presentation without making chat rendering depend on mutable Toolkit configuration, arbitrary tool-name prefixes, unvalidated JSON, or backend-owned UI payloads. Unknown, historical, malformed, and newly introduced tools must remain fully inspectable.

## Decision

### Select renderers only from canonical source-aware identities

Specialized rendering requires both a canonical identity available in the event
contract and successful validation of the payload available in the call's current
lifecycle phase.

- A source-less client tool call may select a renderer only through an exact,
  frontend-owned allowlist of first-party builtin names.
- A provider tool call may select a renderer only through its exact canonical
  provider semantic name.
- A DB-attached Toolkit call remains Generic. Its immutable `toolkit_source`
  identifies product ownership for Activity categorization, but it does not identify
  an immutable operation or payload schema.
- A source-less client call that is not in the builtin allowlist remains Generic.

The frontend must not authorize specialization from a visible-name prefix,
`toolkit_type`, current Toolkit configuration, or a name that merely resembles a
builtin. A future Toolkit-specific renderer requires an immutable canonical operation
identity and versioned payload contract in the event model.

Renderer failure, unknown lifecycle phase, missing required fields, and schema drift
fall back for that call only and do not affect adjacent Activity events.

### Adapt payloads through a pure phase-aware frontend registry

Payload parsing, validation, and semantic adaptation live in a pure frontend
registry outside React components. An adapter has no translation, network, mutable
runtime configuration, or rendering dependency. It receives the original call model
and returns either a discriminated specialized presentation or a typed internal
non-specialization reason:

- `unregistered`;
- `unsupported-phase`;
- `invalid-arguments`;
- `invalid-output`; or
- `adapter-error`.

These reasons support tests and bounded diagnostics only. Every non-specialized result
uses the same user-visible Generic fallback.

Validation is lifecycle-aware:

- `preparing` remains Generic because final arguments may not exist;
- `running` may specialize after argument validation and must not imply
  output-derived facts; and
- terminal calls validate arguments and the renderer-declared output policy:
  `none`, `opaque-text`, or `structured`.

An opaque text output may use deterministic formatting or truncation, but it must not
be semantically interpreted. A structured output contributes semantic facts only
after strict decoding. Schemas reject incompatible shapes while normally tolerating
unknown additive fields unless those fields create semantic ambiguity.

The adapter keeps the original raw argument and output strings separate from the
derived presentation so the shell can fall back safely. Localization belongs to view
components. Errors are isolated around both selection/adaptation and specialized
React rendering so an adapter or component defect cannot break the Activity stream.

### Use one disclosure shell with closed presentation families

Phase 1 client-tool events use one shared disclosure shell. Adapters and family views
do not own the outer row, lifecycle indicator, expand/collapse behavior, focus
handling, accessibility contract, or raw-diagnostic policy. Provider tools remain on
their existing Generic card until a later provider-specific slice implements the same
contract without changing attachment boundaries.

The collapsed event summary is assembled by the shell from structured adapter output:

- a semantic action key;
- a primary subject;
- an optional count or qualifier; and
- the canonical call lifecycle state.

The shell and family views apply a minimum-information rule. Validation does not make
every field display-worthy. The collapsed row shows only the action, primary subject,
and lifecycle state, plus a qualifier only when it materially changes interpretation.
Expanded semantic content prioritizes the primary result and at most a few essential
facts. It omits defaults, empty values, internal limits, repeated labels, and settings
that do not help the user understand the outcome.

The expanded event renders validated family-specific fields and results exactly once.
It does not repeat those values in a universal `Technical details` section. Arguments,
output, and structured metadata become ordinary semantic fields or result blocks when
the family can present them faithfully.

The single-presentation rule applies to the ordinary semantic surface. The separate
Raw data modal is the intentional diagnostic exception and may repeat values that were
derived into the row or semantic body.

A specialized event keeps raw diagnostics outside its semantic body. Within an
expanded Activity, the event row may show a subdued `…` action that opens a separate
`View raw data` modal containing the original arguments and output. The action is
omitted when the call has no raw content. Raw values come byte-for-byte from the
retained argument string and retained deterministic output projection; they are never
reconstructed from the semantic presentation.

The `…` action does not appear on the collapsed Activity summary or create another
inline card or disclosure. Generic rendering does not use this action because its
arguments and output are already the primary expanded content.

The event disclosure and `…` action are sibling controls, never nested buttons. An
event with no semantic body does not open an empty panel; its row remains sufficient,
and the sibling `…` action may still provide raw diagnostics.

Adapters return structured values for one of a small closed set of presentation
families, not translated prose or arbitrary React components. Initial families cover
resource operations, search and lists, commands and processes, patches and changes,
state mutations, collaboration, and provider references. A genuinely distinct
interaction requires an explicit new family variant and review of its fallback,
accessibility, and raw-detail behavior.

Generic rendering uses the same shell and lifecycle rules, with arguments and output
as its primary expanded content because no validated semantic presentation exists.
The shell must avoid nested cards inside Activity. Specialized rendering does not
change attachments, Activity membership or ordering, event identity, or standalone
ownership.

### Roll out complete families behind explicit registry activation

The design defines the complete registry and presentation-family matrix, but adapters
are activated in contract-complete vertical slices. An eligible identity without an
activated adapter remains intentionally Generic; it does not receive a summary-only
or partially validated specialization.

The rollout order is:

1. stable runtime families: resource and list (`read`, `grep`, `glob`), mutation and
   diff (`write`, `edit`, `apply_patch`, `delete`), and process (`exec_command`,
   `write_stdin`);
2. state and collaboration tools, including memory, Goal/Todo, and subagent tools,
   after a prominence and privacy review; and
3. provider tools such as `web_search`, `file_search`, `code_interpreter`, and
   `image_generation`, carrying canonical provider references through the frontend
   view model when their family uses them.

The provider-reference work is a frontend projection change because the canonical
event already carries references. It does not require a backend event, API, or
persistence change. File-exchange and attachment-bearing tools remain governed by the
existing Activity boundary and specialize only when the owning event legitimately
uses a diagnostic tool presentation.

Each family activates only after fixtures cover lifecycle phases, malformed and
drifted payloads, adapter and renderer exceptions, large payloads, single-presentation
of represented fields, and byte-preserved residual raw data when exposed. A faulty
specialization is reverted by removing its exact frontend registry entry without
changing an event contract or introducing mutable adapter behavior.

### Separate structural validation from display prominence

A structurally valid field is not automatically safe or useful in a collapsed
summary. Each presentation family owns an explicit prominence allowlist. Summary
subjects are normalized to one line and bounded by reviewed length and count limits.

Resource families may expose a basename or workspace-relative path only when that
family explicitly permits it. Raw commands, stdin, file content, patch and edit
bodies, memory values, Goal text, prompts and messages, excerpts, arbitrary output,
and credential- or query-bearing URIs remain expanded-only. Structured provider
reference titles and resource names also require explicit family approval; otherwise
the summary uses only a type, count, operation, or lifecycle state. Adapters never
produce free-form summary prose.

Generic fallback is local and visually silent. `unregistered`, `unsupported-phase`,
and validation mismatch are normal compatibility outcomes and do not produce
production error reports. Adapter exceptions and specialized-renderer boundary
exceptions are implementation defects. When an approved frontend logging integration
is available, it may report only the registry identity and version, call kind,
lifecycle phase, bounded reason code, and application version. It must exclude raw or
parsed payload values, paths and subjects, call identifiers unless operationally
required, excerpts, attachment or reference URIs, and exception text that may contain
payload data. This feature does not call a Sentry SDK directly; in the absence of an
approved logging boundary, correctness relies on local fallback and deterministic
tests rather than new production telemetry.

Generic fallback must still succeed when diagnostic reporting fails.

## Consequences

- Known first-party tools can communicate operation and resource context without
  changing backend grouping, execution, or persistence contracts.
- Generic rendering remains the permanent behavior for Toolkit-owned, unknown,
  disabled, malformed, drifted, and not-yet-implemented calls.
- Phase 1 client tools use one disclosure, lifecycle, accessibility,
  single-presentation, Generic fallback, and failure-isolation contract; provider
  tools remain Generic until a later slice adopts the same contract.
- The frontend retains canonical client result metadata for Phase 1. Provider
  references and cancelled/interrupted lifecycle preservation remain Phase 3 work.
- Adapter schemas become reviewed frontend compatibility contracts and require
  drift tests against canonical tool fixtures.
- Specialized summaries intentionally reveal less than expanded raw detail. Adding a
  new prominent field requires a family privacy review even when its structure is
  valid.
- Dynamic Toolkit tools cannot receive semantic detail specialization until the
  canonical event model provides an immutable operation identity and versioned
  payload contract.
- Historical events need no migration or rewrite; removing an exact frontend registry
  entry returns its calls to Generic rendering.

## Alternatives Considered

### Select renderers from visible names regardless of source

Rejected because a Toolkit operation can collide with or resemble a builtin name.
The model-visible name is a routing name, not a canonical semantic contract.

### Select Toolkit renderers from `toolkit_type` and visible name

Rejected because Toolkit source metadata identifies product ownership but not an
immutable operation identity or schema version.

### Let each React component parse its own payload

Rejected because validation, fallback, lifecycle, accessibility, and error handling
would be duplicated and rendering exceptions could escape the compatibility boundary.

### Persist backend-generated presentation models

Rejected because semantic detail remains frontend presentation policy and current
canonical events already contain the Phase 1 source data.

### Build one bespoke component for every tool

Rejected because it creates inconsistent nested cards and duplicates the disclosure
and raw-diagnostic contract. Closed presentation families retain deliberate UX review
without allowing arbitrary renderer-owned React.

### Interpret model-visible textual output

Rejected because output wording is not a stable structured contract. Text stays
opaque unless a registered structured metadata or output decoder succeeds.

### Activate compact summaries before complete detail support

Rejected because a summary-only transition would create a second temporary contract
and ship validation without complete fallback, raw-detail, and lifecycle coverage.

## Migration provenance

- Historical source filename: `0176-render-known-tools-through-validated-frontend-adapters.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
