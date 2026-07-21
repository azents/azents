---
title: "MCP Egress Proxy Historical Decision Reconstruction"
created: 2026-03-19
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: mcp-260319
historical_reconstruction: true
migration_source: "docs/azents/design/mcp-egress-proxy.md"
---

# MCP Egress Proxy Historical Decision Reconstruction

- Snapshot: `mcp-260319`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/mcp-egress-proxy.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### mcp-260319/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Architecture

```
worker pod
  │
  ├── LLM API, DB, Redis → direct connection (not through proxy)
  │
  └── MCP request (mcp_transport.py, mcp_discovery.py)
        │
        ↓
  mcp-egress-proxy (Squid, separate Deployment)
        │
        ├── private IP → blocked
        └── public IP → allowed → external MCP server
```

### Explicit source section: Blocking Policy

Block only at IP level. No domain-level filtering.

```
acl blocked_nets dst 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 127.0.0.0/8 169.254.0.0/16 fd00::/8
http_access deny blocked_nets
http_access allow all
```

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
