---
title: "Return a NamedTuple or frozen dataclass for any function returning more than one value — bare positional tuples break silently when the field order changes."
---

# Structured Multi-Field Returns

Callers unpacking `a, b, c = func()` blow up silently when someone reorders the return tuple. NamedTuple / dataclass fields are looked up by name, so refactors stay explicit.

- ALWAYS use `NamedTuple` or `@dataclass(frozen=True)` for multi-field returns
- AVOID bare `tuple[X, Y, Z]` return types

## Bad

```python
def get_place_stats(place_id: str) -> tuple[int, float, str]:
    return (100, 4.5, "open")
```

## Good

```python
class PlaceStats(NamedTuple):
    review_count: int
    rating: float
    status: str

def get_place_stats(place_id: str) -> PlaceStats:
    return PlaceStats(review_count=100, rating=4.5, status="open")
```
