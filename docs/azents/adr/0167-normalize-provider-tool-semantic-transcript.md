---
title: "ADR-0167: Normalize Provider Tool Semantic Transcript Content"
created: 2026-07-18
tags: [architecture, backend, engine, llm, tools, compaction]
---

# ADR-0167: Normalize Provider Tool Semantic Transcript Content

## Status

Draft. Records decisions confirmed during design discussion.

## Topic

Define a provider-neutral canonical contract that preserves model-visible semantic content from provider-hosted tool output across normal replay, adapter or model changes, and context compaction without adding compaction-specific parsing for every provider tool.

## Context

Azents stores provider-hosted model output as `provider_tool_call` and `provider_tool_result` canonical events with opaque `native_artifact` payloads for strict same-native replay. Canonical fields are the durable source of truth; native artifacts are only compatible replay optimizations.

The current generic compaction renderer includes canonical provider-tool call arguments and result output. However, provider APIs do not expose hosted tools through one uniform call/result shape. For example, OpenAI Responses web search exposes query and source metadata inside a `web_search_call.action` native item, emits no separate tool-result body, and places the synthesized answer and citation annotations in the assistant message. The current canonical web-search call stores `arguments=None`, so compaction and cross-native lowering preserve only that web search occurred, while query, source, and citation metadata remain available only inside the opaque native artifact.

Adding provider-tool-specific parsing directly to compaction would violate the adapter boundary and require compaction changes whenever a new hosted tool is introduced. Depending only on `ProviderToolResultPayload.output` would also miss providers and tools whose meaningful data appears in call items, assistant annotations, generated files, or other native output structures.

## Goals

- Preserve provider-exposed semantic content needed for future model continuation and compaction.
- Keep provider-specific extraction inside adapter output normalizers.
- Give compaction, token estimation, continuity rendering, and cross-native lowering one provider-neutral projection.
- Avoid requiring compaction changes for each newly supported provider-hosted tool.
- Preserve strict native-artifact compatibility and replay rules.
- Bound model-visible content independently from opaque audit/native artifacts.

## Non-goals

- Reconstruct result bodies that a provider does not expose.
- Store complete fetched pages or hidden provider context.
- Make provider-tool execution owned or retryable by the Azents client-tool executor.
- Interpret opaque native artifacts outside their owning adapter.
- Guarantee that every provider exposes equivalent provenance or result detail.

## Current Behavior

- Adapter output normalizers create canonical provider-tool call/result events.
- Same-native lowering may replay compatible native artifacts verbatim.
- Cross-native lowering and compaction use only canonical call arguments and result output.
- Provider-tool results with canonical `output` are preserved generically.
- Hosted tools without a separate result output can lose semantic metadata at the canonical boundary.
- Assistant message normalization preserves text but does not promote provider citation annotations into canonical model-visible content.

## Constraints

- Canonical transcript remains the durable semantic source of truth.
- `NativeArtifact.item` remains opaque outside the adapter that owns it.
- Provider-specific wire types and discriminators must not escape adapter normalizers.
- Canonical content must support deterministic token estimation and bounded compaction rendering.
- File and attachment output continues to use shared `ToolOutput` / FilePart resource policy.
- New canonical fields form a persistent event contract and require migration and compatibility planning.

## Decision Todo

1. Choose the provider-neutral semantic representation for hosted-tool output.
2. Decide whether call arguments, results, provenance, and citations share one ordered content stream or remain separate canonical fields.
3. Define the normalizer obligation and fallback behavior for unknown future provider-tool item types.
4. Define bounding, redaction, and token-accounting policy for promoted semantic content.
5. Define lowering, compaction, continuity, and UI consumers of the normalized content.
6. Define migration behavior for existing events whose semantic content exists only in native artifacts.
7. Define adapter contract and regression-test requirements for adding new provider-hosted tools.

## Confirmed Decisions

### ADR-0167-D1. Normalize provider-tool semantic content at the adapter boundary

Every recognized durable provider-tool output item must produce a provider-neutral semantic projection before it enters the canonical transcript. The projection has four common axes:

- `input`: bounded readable input or action text exposed by the provider;
- `output`: shared `ToolOutput` content exposed by the provider;
- `references`: bounded provider-neutral external or file references;
- `attachments`: materialized user-accessible files.

The provider adapter output normalizer owns native field extraction. Compaction, token estimation, continuity rendering, cross-native lowering, UI projection, and context inspection consume only the canonical projection and never inspect `NativeArtifact.item`.

### ADR-0167-D2. Keep provider-tool call and result event kinds, but share one semantic contract

Keep `provider_tool_call` and `provider_tool_result` as durable event kinds because they remain useful for transcript ordering, UI treatment, and same-native replay. Both payloads use the same nested semantic content contract instead of assuming that input exists only on calls or output exists only on results.

A single native hosted-tool item may therefore carry both semantic input and output even when its event kind is `provider_tool_call`. Adapters do not synthesize a fake result event solely to fit a call/result pair.

### ADR-0167-D3. Use typed references and shared ToolOutput

Semantic `output` uses the existing `ToolOutput` union so text, ModelFile, Attachment, and Artifact handling follows one lowering and lifecycle policy.

Semantic `references` use a small provider-neutral typed record containing reference kind, optional URI, optional title, optional excerpt, and bounded string metadata. Provider-native dictionaries are not copied wholesale into canonical fields.

### ADR-0167-D4. Require explicit semantic extraction for every recognized provider-tool item

Provider-tool item registration and semantic extraction form one adapter-owned contract. Adding a recognized native provider-tool item type requires:

- semantic Azents tool name;
- canonical status mapping;
- event-kind classification;
- semantic input/output/reference extraction;
- contract tests proving canonical compaction and cross-native lowering behavior.

An adapter may explicitly produce empty semantic content when the provider exposes no model-visible information. Silent native-artifact-only preservation for a recognized tool is not accepted.

### ADR-0167-D5. Apply shared bounds before durable storage

Promoted input, output text, excerpts, and reference metadata are bounded before canonical event persistence. Opaque native artifacts remain available for audit and strict same-native replay, but their size and content do not determine model-visible semantic projection.

### ADR-0167-D6. Do not reconstruct unavailable provider results

Azents preserves only information exposed by the provider response. It does not fetch source pages, reconstruct hidden grounding context, or manufacture result text. For hosted Web search, search action/query and exposed source references are canonicalized while the provider-generated assistant answer remains an assistant message.

## Consequences

- New hosted tools require one adapter semantic extractor, but no compaction-specific or cross-native tool branch.
- Same-native replay continues to use strict native artifacts when compatible.
- Cross-native replay and compaction retain provider-exposed semantic content instead of only tool name and status.
- Provider tools whose native item combines invocation and result no longer require artificial call/result splitting.
- Canonical payload growth is bounded and model-visible token accounting becomes deterministic.
- Existing provider-tool event payloads require a data migration to the new nested semantic contract; runtime legacy parsing fallbacks are not introduced.

## Alternatives Considered

### Force every hosted tool into existing arguments and result output

Rejected because provider APIs commonly combine input and output in one item and expose references outside either field. Artificially splitting one item into call/result events would create ordering and replay semantics not present in the provider response.

### Read native artifacts directly during compaction

Rejected because native artifacts are opaque adapter-owned replay optimizations. This would make compaction provider-specific and require a new branch for every hosted tool and adapter.

### Store the complete native item as canonical JSON text

Rejected because it would expose provider schema drift, internal metadata, and potentially sensitive or unbounded data to model input while duplicating the native artifact.
