---
title: "ADR-0071: Replace MCP Per-User OAuth with Toolkit-Level OAuth Connections"
created: 2026-06-23
tags: [backend, engine, security, api]
---

# ADR-0071: Replace MCP Per-User OAuth with Toolkit-Level OAuth Connections

## Context

Azents currently supports MCP per-user OAuth through `auth_type=oauth2_per_user`. That path stores one OAuth token per `(toolkit_id, user_id)` in `mcp_oauth2_tokens`, emits MCP authorization request events when a user has not connected, and disables per-user OAuth toolkits in system sessions.

The product direction is to remove this per-user MCP OAuth surface and make OAuth a toolkit-level connection. Notion, Sentry, and generic remote MCP toolkits should use the same OAuth authorization code + PKCE flow, optionally with Dynamic Client Registration (DCR), but the resulting connection belongs to the `ToolkitConfig` rather than to an individual user.

The change intentionally changes authorization semantics:

- Old behavior: each user connects their own external account.
- New behavior: workspace managers connect the toolkit once, and agent runs using that toolkit use the toolkit's OAuth connection.

This reduces runtime branching, removes user-specific MCP authorization request events, makes OAuth usable from system sessions, and makes Notion/Sentry work as manager-configured service integrations.

## Decision

### ADR-0071-D1: Remove MCP per-user OAuth

Remove `auth_type=oauth2_per_user` and the associated runtime/API/data model surface.

This includes the per-user token table, auth-request/mute table, runtime authorization-request pseudo-tool, and regular-user `user-authorize` flow. Existing per-user tokens must not be promoted into toolkit-level credentials because doing so would convert a user's private grant into a shared capability without explicit manager reconnection.

Existing `oauth2_per_user` toolkit configs are treated as invalid/disabled during migration and must be reconnected by a manager using toolkit-level OAuth.

### ADR-0071-D2: Use `auth_type=oauth2` for toolkit-level MCP OAuth

Use `auth_type=oauth2` as the MCP OAuth auth type after per-user OAuth is removed. Do not introduce `shared` into code, DB, or API names; the connection is toolkit-level by definition.

Generic MCP exposes `oauth2`, and Notion/Sentry use the same generic OAuth infrastructure as provider presets/defaults.

### ADR-0071-D3: Store OAuth client/token state in `mcp_oauth_connections`

Introduce `mcp_oauth_connections` as the toolkit-owned OAuth connection table. It has a unique `toolkit_id` and stores OAuth issuer/resource/endpoints, DCR client metadata, encrypted access/refresh tokens, token expiration, scope, token endpoint auth method, and connection status.

The connection owner remains `ToolkitConfig`; the separate table exists to support token rotation, connection status, row locking, and future queryability.

### ADR-0071-D4: Use manager-only OAuth connect/exchange/disconnect APIs

Replace the per-user OAuth API with manager-only toolkit OAuth connection APIs:

- `POST /toolkit/v1/workspaces/{handle}/toolkit-configs/{id}/oauth/connect`
- `POST /toolkit/v1/workspaces/{handle}/toolkit-configs/{id}/oauth/exchange`
- `DELETE /toolkit/v1/workspaces/{handle}/toolkit-configs/{id}/oauth/connection`

The frontend receives the provider callback and calls the exchange endpoint. State validation binds the callback to the toolkit, workspace, and PKCE verifier.

### ADR-0071-D5: Refresh OAuth tokens lazily under a row lock

Refresh toolkit OAuth tokens at request time. If a token is missing, expired, near expiry, or a tool call returns 401, acquire a row lock on `mcp_oauth_connections`, reload the connection, refresh once if still necessary, atomically store the rotated token set, and retry the MCP call once.

`invalid_grant` is terminal and transitions the connection to `reconnect_required`. Background refresh jobs are out of scope.

### ADR-0071-D6: Show OAuth connection status/actions without warning copy

The toolkit settings UI shows OAuth connection status and actions for OAuth MCP toolkits:

- status: not connected / connected / reconnect required
- issuer
- resource
- scope
- expiration
- connect / reconnect / disconnect actions

Do not add a warning paragraph in this feature. Account identity display and a separate OAuth connection management page are out of scope.

## Consequences

### Positive

- Removes user-specific MCP OAuth runtime branching.
- Makes OAuth MCP toolkits usable in system sessions.
- Gives Notion/Sentry the same configuration model as generic MCP OAuth.
- Avoids unsafe promotion of personal per-user tokens into shared toolkit credentials.
- Makes token refresh safer for rotating refresh tokens such as Notion by using row-level locking.
- Reduces long-term maintenance by replacing two per-user tables with one toolkit-level connection table.

### Negative

- Existing per-user OAuth connections require manager reconnection.
- Users no longer get external-service access scoped to their own account through Notion/Sentry MCP toolkits.
- Generic MCP OAuth support increases provider-compatibility surface area.
- A new DB table/repository/API surface is required.

### Follow-up work

- Provider account identity display can be added later if Notion/Sentry expose a stable way to identify the connected account.
- Revocation endpoint support can be added later; disconnect initially removes the local connection.
- Client ID Metadata Document support is out of scope and can be considered when a target MCP server requires it.

## Alternatives

### Keep per-user OAuth and add toolkit-level OAuth beside it

Rejected. Keeping both paths preserves the highest-complexity runtime and test matrix. The product direction is to remove per-user OAuth rather than keep it as legacy fallback.

### Store toolkit OAuth in `ToolkitConfig.encrypted_credentials`

Rejected. It is simpler initially, but token rotation, row locking, status transitions, and expiration queries are all cleaner with a dedicated connection row.

### Create workspace-provider-level OAuth connections

Rejected for this phase. Workspace-level connections may be useful later, but the current ToolkitConfig ownership model is enough and keeps lifecycle cleanup straightforward.

### Name the new mode `oauth2_shared_dcr`

Rejected. Once per-user OAuth is removed, OAuth is toolkit-level by default; `shared` is redundant and should not leak into code or API names.

### Auto-promote an existing user's token into the toolkit-level connection

Rejected as unsafe. A user's personal grant must not become a toolkit-level capability without explicit manager reconnection.
