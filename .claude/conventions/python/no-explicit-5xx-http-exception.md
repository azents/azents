---
title: "In product API code, do not raise HTTPException for 5xx responses — let unexpected/internal failures propagate so FastAPI/server error handling owns 500s, and never use gateway statuses like 502/503/504 for product API failures."
---

# No Explicit 5xx HTTPException In Product API Code

The product API server is not a gateway. API routes must not deliberately convert internal failures, upstream/service failures, or unexpected states into `HTTPException` with a 5xx status.

- Do not raise `HTTPException(status_code=500)` for internal failures. Let the original exception propagate so FastAPI and the global server error handling convert it to a 500 response and preserve the real exception for observability.
- Do not raise `HTTPException` with 502, 503, or 504 for product API failures. Those statuses describe gateway/proxy semantics and should not be emitted by route code for internal implementation details.
- Use explicit `HTTPException` only for expected client/domain errors that have a stable 4xx contract, such as not found, invalid request state, conflict, unauthorized, or forbidden.
- Service-layer result unions should not model unexpected/internal failures as explicit variants only to let routes map them to 5xx. Unexpected failures should remain exceptions.
- If a dependency failure must be user-visible and handled, model it as a domain-specific expected error and map it to an appropriate 4xx only when the client can act on it. Otherwise, let it propagate.

## Bad

```python
match result:
    case UpstreamFetchFailed():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model listing is unavailable.",
        )
```

```python
except SomeInternalError as exc:
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal operation failed.",
    ) from exc
```

## Good

```python
match result:
    case DomainNotFound():
        raise HTTPException(status_code=404, detail="Resource not found.")
    case Success(value=value):
        return value
```

```python
# Let unexpected dependency/internal failures propagate.
models = await model_listing_service.list_models(integration)
return ModelListResponse(models=models)
```
