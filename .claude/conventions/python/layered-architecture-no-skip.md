---
title: "API routes call services; repositories own SQLAlchemy and transaction lifetimes, composing narrower repositories for atomic database operations."
---

# Layered Architecture, Don't Skip Layers

| Layer | Owns |
| --- | --- |
| `api/` | HTTP request/response, input validation |
| `services/` | Business logic, external I/O, sequencing completed repository operations |
| `repos/` | SQLAlchemy queries, data access, transaction start/commit/rollback |

Routes calling repos skip business validation; services using SQLAlchemy directly leak DB schema into orchestration code. Both make refactoring much harder.

- ALWAYS go Routes → Services → Repos in that direction
- ONLY the repository layer may import from `sqlalchemy`
- AVOID importing from `repos/` inside `api/` routes
- ALWAYS open and finish database transactions inside the repository layer.
- Compose narrower repositories through an orchestration repository when multiple database operations must commit atomically. Share one transaction within that repository composition.
- Services call complete repository operations; they do not receive or pass live database sessions, transactions, or lazy database handles.

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
