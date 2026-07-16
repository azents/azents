---
title: "When Engine-level behavior changes, update every supported lowerer and its tests; only provider-dialect translation may remain isolated to one provider."
---

# Apply Engine Behavior Consistently Across Lowerers

The Engine defines provider-neutral semantics. Lowerers may differ in wire syntax, but must not silently expose different Engine behavior.

- ALWAYS enumerate and update every supported lowerer when an Engine-level contract or behavior changes.
- ALWAYS add or update tests that demonstrate the same Engine semantics through each lowerer.
- Treat changes to Engine inputs, events, tools, lifecycle, validation, or output behavior as shared changes.
- Limit a change to one lowerer only when it solely translates existing shared semantics into provider-specific field names, payload shapes, stream frames, or another provider dialect detail.
- If a provider cannot support shared behavior, represent that limitation explicitly with a capability boundary or unsupported error instead of silently omitting the behavior.

## Bad

```python
# Adds provider-neutral tool behavior to only one lowerer.
class ProviderALowerer:
    def lower_tool(self, tool: EngineTool) -> dict[str, object]:
        return lower_new_engine_tool(tool)
```

## Good

```python
# Implement the shared Engine behavior in every supported lowerer.
for lowerer in all_supported_lowerers:
    assert lowerer.lower_tool(new_engine_tool) == expected_provider_request(lowerer)
```
