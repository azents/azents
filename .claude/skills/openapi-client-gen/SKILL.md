---
name: openapi-client-gen
description: Regenerate Azents API clients from OpenAPI specifications. Use when API routes are added or modified, or when the user asks to regenerate clients, update OpenAPI spec, or sync API changes.
---

# OpenAPI Client Generation

Regenerate API clients from Azents OpenAPI specifications.

## Public API

1. Generate OpenAPI specs:

```bash
cd /path/to/azents/python/apps/azents
uv run python src/cli/dump_openapi.py
```

2. Regenerate Python client:

```bash
cd /path/to/azents/python/libs/azents-public-client
make generate
```

3. Regenerate TypeScript client:

```bash
cd /path/to/azents/typescript
pnpm run generate --filter=@azents/public-client
```

## Admin API

1. Generate OpenAPI specs:

```bash
cd /path/to/azents/python/apps/azents
uv run python src/cli/dump_openapi.py
```

2. Regenerate Python client:

```bash
cd /path/to/azents/python/libs/azents-admin-client
make generate
```

3. Regenerate TypeScript client:

```bash
cd /path/to/azents/typescript
pnpm run generate --filter=@azents/admin-client
```

## When to Run

- API routes are added or modified.
- Request/response schemas change.
- New endpoints are added.
- Endpoint paths or methods change.

## Notes

- TypeScript clients use @hey-api/openapi-ts.
- Generated files are typically gitignored; do not manually edit them.
- After generation, run type checks to ensure compatibility.
