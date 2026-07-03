---
title: "Write Python docstrings in Sphinx style with no type annotations inside the docstring — types belong in type hints, not in :param: / :type: lines."
---

# Sphinx-Style Docstrings (No Types)

Pyright already enforces type hints. Repeating them in the docstring duplicates the truth and lets the two drift.

- ALWAYS use Sphinx field syntax (`:param x:`, `:returns:`, `:raises:`)
- NEVER write types in the docstring — leave that to the function signature

## Bad

```python
def get_place(place_id: str) -> Place | None:
    """Fetch a Place.

    :param str place_id: ID of the place
    :returns Place | None: fetched place
    """
```

## Good

```python
def get_place(place_id: str) -> Place | None:
    """Fetch a Place.

    :param place_id: ID of the place
    :returns: fetched place, or None when it does not exist
    """
```
