---
title: In azents-web, call public API endpoints through generated @azents/public-client functions instead of raw ctx.apiClient HTTP methods or hand-written internal API fetch URLs, so frontend paths stay aligned with OpenAPI.
---

# Use Generated Public API Client

OpenAPI path drift can surface as production-only 404s when frontend code hand-writes API URLs.

- ALWAYS use generated functions from `@azents/public-client` for public API endpoints that exist in the azents OpenAPI spec.
- AVOID raw `ctx.apiClient.get/post/patch/delete(...)` calls in tRPC routers when a generated SDK function exists.
- AVOID hand-written `fetch(`${config.internalApiUrl}/...`)` URLs in route handlers when a generated SDK function can express the request.
- If a route handler must relay a bearer token, create a configured generated client and pass it via the SDK function's `client` option.
- Exception: endpoints not present in the generated client may use a raw call, but add a short TODO or follow-up to regenerate/update the client.

## Bad

```ts
const { data } = await ctx.apiClient.get({
  url: "/model-config/v1/workspaces/{handle}/model-configs",
  path: { handle },
  throwOnError: true,
});
```

## Good

```ts
const { data } = await modelconfigV1ListModelConfigs({
  client: ctx.apiClient,
  path: { handle },
  throwOnError: true,
});
```
