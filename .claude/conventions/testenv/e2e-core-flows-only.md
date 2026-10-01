---
title: "Use E2E only for critical user journeys and real system boundaries; cover condition matrices, branches, and edge cases in unit or integration tests instead of preserving E2E counts."
---

# Keep E2E Focused on Critical Flows

E2E proves that independently deployed parts work together. It is not the exhaustive home for product logic.

- ALWAYS keep E2E coverage for critical user-visible flows and behavior that requires a real browser, network, process, image, provider, restart, or deployment boundary.
- ALWAYS cover condition combinations, internal branches, validation permutations, and edge cases at the narrowest unit or integration layer that can prove them.
- Preserve behavioral coverage when moving a scenario to a faster layer; do not retain an E2E case merely to keep the E2E test count unchanged.

## Bad

```python
@pytest.mark.parametrize("configured_limit", [None, 0, 1, 4096, 8192])
async def test_every_context_limit_branch_through_full_runtime(configured_limit):
    ...
```

## Good

```python
@pytest.mark.parametrize("configured_limit", [None, 0, 1, 4096, 8192])
def test_context_limit_resolution(configured_limit):
    ...

async def test_selected_context_limit_reaches_the_running_agent():
    ...
```
