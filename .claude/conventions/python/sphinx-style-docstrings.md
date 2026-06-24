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
    """Place 를 조회한다.

    :param str place_id: place 의 ID
    :returns Place | None: 조회된 place
    """
```

## Good

```python
def get_place(place_id: str) -> Place | None:
    """Place 를 조회한다.

    :param place_id: place 의 ID
    :returns: 조회된 place. 존재하지 않으면 None
    """
```
