---
title: "Select Provider-Specific Tool Dialects for Apply-Patch Historical Requirements Reconstruction"
created: 2026-07-21
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: patch-260721
historical_reconstruction: true
migration_source: "docs/azents/adr/0179-apply-patch-provider-tool-dialects.md"
---

# Select Provider-Specific Tool Dialects for Apply-Patch Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `patch-260721`
- Source: `docs/azents/adr/patch-260721-patch-dialects.md`
- Historical source date basis: `2026-07-21`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

[ambiguous historical ADR reference](../notes/legacy-docid-migration-ambiguity-manifest-2026-07-21.md#ambiguity-ref-197) introduced the model-visible `apply_patch` client tool as an ordinary JSON-schema function tool for OpenAI-developed GPT-family models. Its input carries an absolute Runtime `base_path` and one complete V4A document in the `patch` string. The Runtime Runner owns strict V4A parsing, path confinement, preflight, staging, optimistic revalidation, deterministic commit ordering, typed terminal results, and exact no-rollback partial-failure reporting.

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

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

- Remove JSON string escaping from `apply_patch` input when the selected provider/model has a verified plaintext custom-tool protocol.
- Preserve ordinary JSON function-tool delivery as a preselected fallback for compatible non-OpenAI models.
- Keep one canonical `apply_patch` execution handler and one Runner `file.apply_patch` operation.
- Preserve the exact native call/output dialect required to replay a durable transcript safely.
- Make tool dialect selection deterministic before provider dispatch rather than retrying through a second dialect after a failed or ambiguous model call.
- Keep unsupported providers and models fail-closed.

## Non-goals

- Using OpenAI's provider-native `type=apply_patch` operation protocol in this change.
- Translating a failed custom call into an inline function-tool retry.
- Changing Runtime patch grammar or filesystem semantics.
- Making every Azents client tool freeform.
- Treating an OpenAI-compatible endpoint or OpenAI-developed model identity alone as proof of custom-tool support.
- Persisting provider credentials, raw request frames, or raw patch content in new metadata.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

- One prepared model request exposes exactly one `apply_patch` dialect under the name `apply_patch`.
- Initial non-OpenAI function fallback remains limited to semantically eligible
  OpenAI-developed GPT models on routes with an independently verified function
  transport profile.
- A provider failure never triggers automatic resubmission through another dialect.
- A durable call is executed at most once under the existing call identity and foreground-tool ownership contract.
- Function and custom calls must lower back to their matching provider call/output item pairs.
- Model switches and provider switches must lower older calls through a safe canonical representation or an exact compatible native artifact; they must not relabel old custom calls as function calls or vice versa.
- Tool Search, declaration budgeting, prompt projection, execution lookup, cancellation, active-tool projection, compaction, context inspection, and frontend rendering continue to use one prepared Tool Catalog snapshot.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
