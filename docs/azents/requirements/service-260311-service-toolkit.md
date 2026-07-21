---
title: "Service Toolkit Design Discussion Historical Requirements Reconstruction"
created: 2026-03-11
tags: [documentation, historical-reconstruction, migration]
document_role: primary
document_type: requirements
snapshot_id: service-260311
historical_reconstruction: true
migration_source: "docs/azents/adr/0024-service-toolkit.md"
---

# Service Toolkit Design Discussion Historical Requirements Reconstruction

> This is a provenance-marked historical reconstruction, not newly approved product intent.
> It contains only statements recoverable from the source document. Unknown intent remains explicitly unknown.

- Snapshot: `service-260311`
- Source: `docs/azents/adr/service-260311-service-toolkit.md`
- Historical source date basis: `2026-03-11`
- Requester confirmation of the historical reconstruction: not recorded; confirmation is required before treating this as approved intent.

## Problem

if at.toolkit_type == ToolkitType.MCP:
    # per-user OAuth2: look up user token + refresh on expiry (~20 lines)
    # create per_user_auth context (~15 lines)
    definition = _make_mcp_definition(toolkit.credentials, ...)
else:
    validated_config = type(definition).validate_config(toolkit.config)
```

**Conclusion**: add a `resolve()` method to `ToolkitProvider` ABC and encapsulate credential logic inside each Provider.

```python
class ToolkitProvider(ABC, Generic[ConfigT]):
    @abstractmethod
    async def resolve(self, context: ResolveContext) -> "ToolkitProvider[ConfigT]":
        """Resolve per-config credentials. Return a new instance if needed."""
        ...
```

Then resolve.py only calls `provider.resolve(context)` without knowing Provider type. DB dependencies such as token repositories are injected into Provider constructors.

## Primary Actor

Unknown — the historical source does not state this explicitly.

## Primary Scenario

Unknown — the historical source does not state this explicitly.

## Supporting Scenarios

Unknown — the historical source does not state this explicitly.

## Goals

Unknown — the historical source does not state this explicitly.

## Non-goals

Unknown — the historical source does not state this explicitly.

## Requirements

Unknown — the historical source does not state this explicitly.

## Fixed Constraints

Unknown — the historical source does not state this explicitly.

## Open Assumptions

Unknown — the historical source does not state this explicitly.

## Historical Unknowns

- Explicit requester confirmation and original acceptance criteria are unknown unless stated above.
- Any product intent not quoted or paraphrased from the source remains unknown.
