---
title: "nointern Core Concepts Historical Decision Reconstruction"
created: 2026-02-07
tags: [architecture, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: core-260207
historical_reconstruction: true
migration_source: "docs/azents/design/core-concepts.md"
---

# nointern Core Concepts Historical Decision Reconstruction

- Snapshot: `core-260207`
- Status: historical reconstruction; not a newly accepted decision.
- Source Design: `docs/azents/design/core-concepts.md`
- Original requester confirmation: not recorded in this reconstruction.

## Reconstructed Decisions

### core-260207/ADR-D1 — Explicit decisions recoverable from the source Design

The following sections are copied only from explicit source Design text. No additional intent is inferred.

### Explicit source section: Depth constraint

```python
MAX_TEAM_DEPTH = 3

def can_create_sub_team(parent_team: Team) -> bool:
    return parent_team.depth < MAX_TEAM_DEPTH
```

### Explicit source section: Architecture comparison

| Item | Existing approach (skill-only) | nointern (platform-mediated) |
|------|----------------------|--------------------------|
| Credential access | agent accesses directly | only platform accesses; agent cannot access |
| Prompt Injection risk | credentials can leak | no credentials in context to leak |
| Tool integration | agent directly integrates through code | MCP-based, mediated by platform |
| Enterprise Readiness | self-hosting, personal responsibility | structure explainable in SOC 2 audit |
| OAuth management | user manages directly | platform manages token lifecycle |

## Historical Unknowns

- Decision acceptance date, rejected alternatives, and requester confirmation are unknown unless explicit in the source.
