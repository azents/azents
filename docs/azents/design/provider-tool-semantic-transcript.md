---
title: "Provider Tool Semantic Transcript Design"
created: 2026-07-18
updated: 2026-07-18
tags: [backend, engine, llm, tools, compaction]
---

# Provider Tool Semantic Transcript Design

## Problem

Provider-hosted tools expose durable model-relevant information through different native response shapes. Some providers emit separate call and result items, while others combine action, result, references, and generated resources in one output item. The current canonical provider-tool contract assumes that call arguments belong to `provider_tool_call` and result content belongs to `provider_tool_result`.

This causes recognized hosted tools such as OpenAI Responses Web search to preserve query and source information only inside opaque `native_artifact`. Same-native replay may retain that information, but compaction and cross-native lowering use canonical fields and lose it. Adding provider-specific compaction parsing would repeat this problem whenever a new hosted tool or adapter is added.

## Goals

- Normalize all provider-exposed model-relevant hosted-tool content into one provider-neutral contract.
- Make compaction, continuity rendering, token estimation, context inspection, and cross-native lowering generic consumers.
- Keep provider-native extraction inside output normalizers.
- Preserve strict same-native artifact replay.
- Support tools whose input and output occur in one native item.
- Bound canonical content before persistence.
- Make semantic extraction a required part of adding a recognized provider tool.

## Non-goals

- Fetch or persist provider-hidden search result bodies.
- Reconstruct source documents from URLs.
- Change client-tool execution or recovery semantics.
- Add provider tool cancellation or retries.
- Replay incompatible native artifacts.
- Add runtime fallback parsing for legacy provider-tool payloads.

## Current Behavior

Canonical payloads use separate shapes:

```text
ProviderToolCallPayload
  call_id
  name
  arguments
  status
  native_artifact

ProviderToolResultPayload
  call_id
  name
  status
  output
  attachments
  native_artifact
```

The compaction renderer and cross-native lowerer read `arguments` and `output`, but never inspect native artifacts. OpenAI Web search stores `action.query` and `action.sources` inside the native artifact while canonical `arguments` is null and no result event is emitted.

## Proposed Canonical Contract

Introduce shared nested semantic content used by both provider-tool payloads.

```text
ProviderToolSemanticContent
  input: string | null
  output: ToolOutput
  references: ProviderToolReference[]

ProviderToolReference
  kind: url | file | other
  uri: string | null
  title: string | null
  excerpt: string | null
  metadata: dict[string, string]

ProviderToolCallPayload
  call_id
  name
  status
  semantic
  attachments
  native_artifact

ProviderToolResultPayload
  call_id
  name
  status
  semantic
  attachments
  native_artifact
```

`input` is readable text. Structured provider input is rendered as stable compact JSON by the owning adapter. `output` reuses `ToolOutput` so output text and file resources follow the same policy as client-tool results. References are structured separately because URLs, file identities, titles, and excerpts must survive compaction without becoming provider-native JSON.

Both event kinds carry the same semantic structure. A native item may contain input and output in either event kind. Event kind describes the observed provider item and transcript role; it does not restrict semantic fields.

## Provider Item Registry

Responses output normalization uses one registry for recognized durable hosted-tool output item types. Each registration supplies:

- native item type;
- semantic Azents tool name;
- durable event kind;
- canonical status mapper;
- semantic extractor;
- optional transient file extractor.

The same item-type registry is reused by provider-tool activity observation where the native stream supplies complete output items. Typed lifecycle event extraction remains adapter-specific, but it must resolve to the same semantic tool name and status vocabulary.

Adding a recognized item type without semantic extraction is a test failure. An extractor may intentionally return empty semantic content when the provider exposes no content.

## Initial Semantic Extraction

### Web search

- Input: action type plus exposed query, query list, URL, or find pattern.
- Output: empty unless the provider exposes result text.
- References: action source URLs.
- Assistant answer remains an assistant message.

### File search

- Input: query list.
- Output: bounded result text.
- References: file ID, filename, score metadata, and bounded excerpt.

### Code interpreter

- Input: code.
- Output: logs and other exposed text.
- References: none by default.
- Output images use shared provider file materialization when supported; otherwise a bounded reference or placeholder is retained.

### Image generation

- Input: exposed action or prompt when available.
- Output: materialized `FileOutputPart` after provider output admission.
- Attachments: existing ExchangeFile resources.

### MCP and future hosted tools

- Input/output/error fields are mapped to semantic input and output.
- Resource or URL fields become references.
- Unknown provider-native metadata remains only in the native artifact.

## Rendering and Lowering

One shared renderer converts provider-tool semantic content to readable text:

```text
[Provider tool call: web_search completed]
Input:
{"query":"Azents compaction","type":"search"}
References:
- https://example.com
```

The renderer is used by:

- compaction summary input;
- continuity excerpts;
- token estimation;
- canonical cross-native lowering;
- context-inspector model-visible projection.

Same-native lowering still prefers the compatible native artifact. The semantic renderer is the fallback contract whenever native replay is unavailable.

Provider-tool attachments and `ToolOutput` FileParts continue through existing file-part lowering and availability filters.

## Bounding and Redaction

- Semantic input uses stable compact JSON and a shared text cap.
- Output text uses the existing tool-output hard cap.
- Reference count, URI length, title length, excerpt length, and metadata entries use explicit shared limits.
- Provider dictionaries are allowlisted by each extractor; complete native objects are never copied into semantic metadata.
- Credentials, request headers, provider IDs, encrypted reasoning, and raw file bodies remain excluded.
- Native artifact storage and strict replay policy remain unchanged.

## Data Migration

A new migration rewrites existing provider-tool JSON payloads into the nested semantic contract:

- existing call `arguments` becomes semantic input;
- existing result `output` becomes semantic output;
- references are empty;
- existing attachments remain attachments;
- removed legacy canonical fields are deleted from payload JSON.

The migration does not inspect or backfill provider-native artifacts. Runtime payload models require the new semantic contract after migration and provide no legacy parsing fallback.

## Error Handling

- Malformed optional native semantic fields are ignored by narrow extractor helpers while the native artifact remains durable.
- Missing required provider-tool identity continues to produce `unknown_adapter_output` instead of an invalid provider-tool event.
- Oversized semantic fields are deterministically bounded, not rejected after the provider call completes.
- File materialization failure follows existing provider-output admission failure behavior.
- A recognized registry entry without an extractor is a startup or test-time programming failure, not a runtime empty fallback.

## Security and Privacy

Canonical projection contains only provider-exposed model-visible content selected through adapter allowlists. Raw provider response dictionaries are not serialized into prompts. Reference metadata is string-bounded and excludes unknown keys. Existing native artifacts remain audit data and are not made model-visible by this design.

## Rollout

1. Add canonical types and payload migration.
2. Add registry-based semantic normalization for current Responses hosted-tool items.
3. Switch generic renderers, lowering, token estimation, and continuity to semantic content.
4. Add contract and regression tests.
5. Promote behavior into current specs after validation.

No feature flag or dual-write period is used. Migration and runtime cut over atomically.

## Test Strategy

### Unit and contract matrix

| Area | Cases |
| --- | --- |
| Canonical schema | call/result accept the same semantic structure; legacy fields are rejected after migration |
| Web search | query/action/source URLs survive canonicalization, cross-native lowering, and compaction |
| File search | queries, result text, file references, score metadata, and excerpts are bounded and retained |
| Code interpreter | code and logs survive; image outputs follow file policy |
| Image generation | materialized file output and attachments remain available |
| Empty provider content | explicit empty semantic projection preserves name/status without invented output |
| Same-native replay | compatible artifact remains verbatim and semantic fallback is unused |
| Cross-native replay | native artifact is rejected and semantic content is rendered |
| Compaction | semantic input/output/references enter summary input; native artifact does not |
| Token estimation | estimates exactly the generic semantic projection and bounded file/reference metadata |
| Migration | old call/result JSON is rewritten and parsed only through the new contract |

### E2E primary validation

Use an Agent with hosted Web search enabled and a deterministic provider fixture that emits a Web-search item with query/source metadata followed by an assistant answer.

1. Run a Web-search turn and verify durable chat/context inspection contains normalized provider-tool semantic data.
2. Force compaction with a small configured context limit.
3. Continue with an incompatible target model fixture so native replay cannot apply.
4. Verify the next model request contains the query and source reference through canonical semantic lowering.
5. Verify the assistant answer remains separate and the provider native artifact is not rendered into prompt text.

The E2E fixture must provide a deterministic Responses event stream and capture the next model request. It requires no external Web-search credential. A live OpenAI test is optional diagnostic evidence only and must be skipped when credentials or hosted-tool availability are absent; deterministic E2E failure is blocking.

### Evidence

- Python Ruff, Pyright, and targeted/full Pytest output.
- Migration upgrade test output.
- Deterministic E2E request capture showing semantic content before and after compaction.
- Diff-to-spec comparison during spec promotion.

## Alternatives

### Reuse only call arguments and result output

Rejected because provider tools commonly combine input and output or expose references outside both fields.

### Parse native artifacts in compaction

Rejected because it violates adapter ownership and creates provider-specific compaction branches.

### Store native JSON as model-visible text

Rejected because it is unbounded, provider-specific, and may expose non-semantic or sensitive fields.

### Replace call/result event kinds with one new provider-tool event kind

Not required. Shared semantic content removes the field-location assumption while preserving useful existing event and UI semantics.
