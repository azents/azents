---
title: "API routes call services, services call repositories, repositories own SQLAlchemy — never let routes call repositories directly or services touch SQLAlchemy. Applies to azents and azents, which both follow this layering."
---

# Layered Architecture, Don't Skip Layers

| Layer | Owns |
| --- | --- |
| `api/` | HTTP request/response, input validation |
| `services/` | Business logic, orchestration across repos |
| `repos/` | SQLAlchemy queries, data access |

Routes calling repos skip business validation; services using SQLAlchemy directly leak DB schema into orchestration code. Both make refactoring much harder.

- ALWAYS go Routes → Services → Repos in that direction
- ONLY the repository layer may import from `sqlalchemy`
- AVOID importing from `repos/` inside `api/` routes

## Bad

```python
# api/routes/places.py
from azents.repos.place_repo import PlaceRepo  # api importing repo directly

@router.get("/places/{id}")
async def get_place(id: str, repo: PlaceRepo = Depends()):
    return await repo.get(id)
```

## Good

```python
# api/routes/places.py
from azents.services.place_service import PlaceService

@router.get("/places/{id}")
async def get_place(id: str, svc: PlaceService = Depends()):
    return await svc.get_place(id)
```
