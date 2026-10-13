---
title: When removing a feature, remove its obsolete tests instead of writing or retaining tests that only assert the deleted feature is absent.
---

# Remove Obsolete Feature Tests

- Do not write or retain tests and assertions whose sole purpose is to verify that a deleted feature is absent.
- Remove those tests and assertions when removing the feature.

## Bad

```python
assert "deleted_tool" not in exposed_tools
```

## Good

Remove the deleted feature's test and its absence assertions.
