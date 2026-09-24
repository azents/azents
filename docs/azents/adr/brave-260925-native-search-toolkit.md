---
title: "Brave Search Native Toolkit Decisions"
created: 2026-09-25
tags: [agent, toolkit, search, architecture]
document_role: primary
document_type: adr
snapshot_id: brave-260925
---

# Brave Search Native Toolkit Decisions

- Snapshot: `brave-260925`
- Requirements: [brave-260925/REQ](../requirements/brave-260925-native-search-toolkit.md)
- Document reference: `brave-260925/ADR`
- Decision owner: requester (Collaborative mode)

## Fixed Outcomes

- Search capabilities and credential ownership are specified in `brave-260925/REQ-1`, `REQ-2`, and `REQ-6`.
- Image search displays bounded results directly as part of its own tool result, without a follow-up tool call, under `brave-260925/REQ-3` and `REQ-4`.
- Existing Conversation and Toolkit Specs provide distinct model-only FileParts, user-visible Exchange attachments, and Runtime-free remote Toolkit execution. The External Channel capability owns publication; Brave search returns image and source URLs under `brave-260925/REQ-5`.

## Decision Map

- [x] `brave-260925/ADR-D1`: Use a dedicated direct Brave Search API client instead of operating Brave's official MCP server. Accepted by the requester on 2026-09-25.

No other material design choice is currently identified. Result count, response shaping within established bounds, and local module organization remain agent-owned implementation details. If feasibility research reveals another material choice, add it to this map before making it.

## brave-260925/ADR-D1 — Direct Brave Search API integration (accepted)

**Authority:** `brave-260925/REQ-1`, `REQ-2`, `REQ-3`, `REQ-6`; existing Toolkit credential, MCP, and file-output boundaries.

**Question:** Should the key-backed native Toolkit obtain the five Brave result types directly from Brave Search HTTP APIs, or operate Brave's official MCP server behind the Toolkit?

**Option A — Direct Brave API client (accepted).** Azents owns a narrow, typed provider boundary for five documented endpoints and exposes static native tools. This avoids an additional Node process and per-credential MCP server lifecycle. Image results can be converted directly into the existing ModelFile and Exchange output types before the same tool call finishes. The trade-off is that Azents owns endpoint request/response adaptation, retry/limit handling, and version drift. The requester explicitly approved the exception to the repository's preference for a supported external-service SDK: the official Brave project identified here is an MCP server rather than a Python SDK for Azents's native provider.

**Option B — Brave's official MCP server.** Azents owns a native Toolkit facade and operates/configures the provider-maintained MCP server, then adapts its MCP results to existing Azents image output types. Brave owns the upstream Search API protocol mapping, and image-search output is URL/metadata based. The trade-off is a separately operated Node/MCP service or per-key process lifecycle, secure key routing between Toolkit credentials and that service, MCP snapshot/discovery availability, and a custom image-delivery adapter. Azents currently supports remote MCP connections rather than per-Toolkit local stdio sidecars; no public hosted Brave MCP endpoint is established by the examined official package metadata.

**Decision:** Adopt Option A. On 2026-09-25, the requester selected direct API integration specifically to avoid operating Option B's MCP server. The direct HTTP exception applies to this five-endpoint Brave Search integration, not to other provider operations. Retain a fixed upstream host, typed and bounded request/response mapping, and no Runtime-side API-key injection.

**Rejected alternative:** Option B requires Azents to run and secure a separate MCP service or per-credential process despite the requirement that the user only configure an API key. Its MCP image result still needs Azents-specific model and user-visible image output adaptation.
