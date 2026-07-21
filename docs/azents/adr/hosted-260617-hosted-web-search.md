---
title: "Provider-hosted web search runs through normalized capability and Agent opt-in"
created: 2026-06-17
tags: [architecture, backend, engine, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: hosted-260617
historical_reconstruction: true
migration_source: "docs/azents/adr/0064-provider-hosted-web-search.md"
---

# hosted-260617/ADR: Provider-hosted web search runs through normalized capability and Agent opt-in

## Context

Azents aligns Agent form and runtime decisions through `normalized_capabilities` in model catalog snapshot. `web_search` is a hosted tool executed server-side by provider, and each provider/model can enable the same semantic capability in different ways.

- OpenAI / ChatGPT OAuth family receives web search as Responses tool definition.
- Gemini family receives Google Search grounding tool definition.
- Anthropic family receives versioned server tool definition.
- Some LiteLLM-compatible providers may require separate request parameter.

Existing code already has `BuiltinToolSpec`, Agent `model_parameters.builtin_tools`, catalog `built_in_tools.supported`, and canonical `provider_tool_call` / `provider_tool_result` events. However, current event runtime does not lower Agent-enabled hosted tool to native LiteLLM Responses request.

## Decision

### hosted-260617/ADR-D1. Agent settings store only semantic capability id `web_search`

Agent does not store provider-specific tool id.

`model_parameters.builtin_tools` stores only semantic hosted tool setting in shape `{ "name": "web_search", "config": {...} }`. Runtime lowerer decides native provider names for OpenAI, Gemini, Anthropic, etc. based on target provider/model/developer.

### hosted-260617/ADR-D2. Model capability means selectability; execution is Agent opt-in

`normalized_capabilities.built_in_tools.supported` means only list of hosted tools selectable for that model. Capability presence does not automatically insert tool into Agent run.

To actually enable hosted web search in Agent run, Agent settings must explicitly include `web_search` in `model_parameters.builtin_tools`. When model selection changes, frontend resets existing hosted tool selections.

### hosted-260617/ADR-D3. LiteLLM Responses lowerer creates both model kwargs and hosted tool request surface

Native request shape can span both `tools` and `kwargs` depending on provider. Therefore `LiteLLMResponsesLowerer` lowers transcript input, client tools, model generation/transport kwargs, and hosted tools together into native request.

`EngineAdapter` passes semantic information from RunRequest to lowerer, and hosted-tool lowering helper inside lowerer creates native `tools` / `kwargs`.

### hosted-260617/ADR-D4. Provider-hosted web search results are stored as canonical provider tool events

Web search executed by provider is not re-executed as Azents client tool. Native output is stored as `provider_tool_call` / `provider_tool_result` canonical events, and same-target replay prefers `native_artifact`. If model changes and native replay is impossible, it degrades to normal assistant text.

### hosted-260617/ADR-D5. Gemini web search allows main Agent tool combination without forcing subagent

Agent using Gemini web search is not forced into subagent split. Assuming Gemini 3 family supports built-in tool + function tool combination, first implementation only validates model capability. If specific provider/model endpoint rejects combination, later block it through catalog override or model-specific constraint.

## Consequences

### Positive

- Agent settings and public API are not tied to provider-specific hosted tool names.
- Model catalog capability sync does not automatically change existing Agent behavior.
- Differences in hosted tool request shape are localized inside lowerer.
- Provider tool result is preserved as canonical transcript, giving clear degrade path when model changes.

### Negative / Trade-offs

- Actual provider/LiteLLM request shape drift must be tracked through lowerer helper and live verification.
- If catalog source provides incorrect `web_search` capability, Agent form may expose the option. Runtime validation blocks with pre-run failure.
- Since subagent split is not forced, if Gemini endpoint combination restriction reappears, model-specific constraint must be added.

## Alternatives

### Store provider-specific tool ids on Agent

This stores `openai_web_search`, `google_search`, `anthropic_web_search` in Agent settings separately. Rejected because Provider switch would break Agent settings and frontend/API would need to know provider naming.

### Automatically enable web search when capability exists

Existing Agent answers may change as soon as catalog sync adds model capability. Cost, latency, and external information intake policy should also be explicit decision by Agent owner. Rejected.

### Force Gemini web search Agent into hidden subagent

This can bypass tool-combination restriction, but greatly complicates session, transcript, permission, and UX boundaries. Rejected for first implementation scope assuming Gemini 3 combination support.

## Migration provenance

- Historical source filename: `0064-provider-hosted-web-search.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
