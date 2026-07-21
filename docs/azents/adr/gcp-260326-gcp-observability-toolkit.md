---
title: "GCP Toolkit — Google Hosted Remote MCP Historical Decision Reconstruction"
created: 2026-03-26
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: gcp-260326
historical_reconstruction: true
migration_source: "docs/azents/design/gcp-observability-toolkit.md"
---

# GCP Toolkit — Google Hosted Remote MCP Historical Decision Reconstruction

- Snapshot: `gcp-260326`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/gcp-observability-toolkit.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### gcp-260326/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Comparison with previous architecture

| Item | Previous design (stdio) | Current design (Hosted HTTP) |
|------|-------------------|------------------------|
| Transport | stdio → mcp-proxy → HTTP SSE | direct HTTPS |
| Sidecar | mcp-proxy sidecar needed | unnecessary |
| Auth | SA Key → `GOOGLE_APPLICATION_CREDENTIALS` | SA Key → JWT → Bearer token |
| Server management | MCP server preinstalled in image | managed by Google |
| Tool updates | image rebuild | automatic (Google-side update) |
| Cold start | Pod creation + MCP server start | none (HTTP immediate connection) |
| Infra change | Pod spec, ConfigMap, Secret | none |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
