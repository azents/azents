---
title: "Slack BYOA Discussion — Discussion Points and Decisions"
created: 2026-04-14
tags: [backend, api, frontend, historical-reconstruction, migration]
document_role: primary
document_type: adr
snapshot_id: slack-260414
historical_reconstruction: true
migration_source: "docs/azents/adr/0026-slack-byoa.md"
---

> 📌 **Related design document**: [slack-260414-slack-byoa.md](../design/slack-260414-slack-byoa.md)
>
> This document records design-stage discussion. See the linked document for the final design and implementation state.

# slack-260414/ADR: Slack BYOA Real Implementation — Discussion Points and Decisions

## Background

BYOA (Bring Your Own App) scaffolding exists—DB model, service, API, frontend—but it does not work end-to-end. This document summarizes design decisions for solving six core gaps.

## Discussion Point 1: Event Verification & Routing Architecture

### Problem

The current Bolt app is created with `signing_secret=slack_config.signing_secret`, a single Platform App secret. Each BYOA app has its own signing secret, so signature verification fails and events cannot be received.

### Options

**A) Single endpoint + dynamic signing secret lookup by parsing body**

- Receive all app events through one endpoint: `/slack/v1/events`.
- Parse body to extract `api_app_id` → look up signing secret in DB → verify.
- Pros: simple endpoint management.
- **Cons: `url_verification` request has no `api_app_id`**, so the app cannot be identified.

**B) Per-app endpoint, separate path for BYOA**

- Platform: `/slack/v1/events`, unchanged.
- BYOA: `/slack/v1/apps/{slack_app_id}/events`, new.
- Identify app from URL path → look up signing secret → verify.
- Pros: can correctly verify every request, including url_verification.
- Cons: BYOA manifest must separately guide the user to set event URL.

**C) Multiple Bolt instances, one Bolt app per Slack app**

- Pros: can use Bolt built-in verification.
- Cons: memory usage grows with app count; duplicate handler registration.

### ~~Decision: B — per-app endpoint~~ → decision changed to A — single endpoint

> Discussion #2550 changed the decision from per-app endpoint to single endpoint so both flows, creating a new app and connecting an existing app, are covered.

**Why skipping signature verification for `url_verification` is safe:**

1. `url_verification` only returns a challenge string and changes no server state.
2. If an attacker sends a fake `url_verification`, they only receive the challenge response, which is harmless.
3. Current code already responds to `url_verification` directly without Bolt signature verification.

**Advantages of single endpoint:**

1. Event URL can be included in the manifest (`{api_url}/slack/v1/events`), removing URL copy-paste by users.
2. URL is universal, so QA flow does not need URL changes.
3. Existing endpoint is reused; no new path is needed.

**Verification flow:**

1. `url_verification` → respond with challenge without signature verification, same as current code.
2. `event_callback` → extract `api_app_id` → DB lookup for BYOA → fallback to Platform config if missing → verify signature.
3. Delegate to Bolt with `request_verification_enabled=False`.

**URL design after change:**

- Events: `/slack/v1/events`, existing endpoint, both Platform + BYOA.
- Interactions: `/slack/v1/interactions`, existing endpoint, both Platform + BYOA.

## Discussion Point 2: DB Schema Change Scope

### Problem

The unique constraint `uq_slack_installations_workspace_id` allows only one installation per workspace. The original design says: multiple BYOA apps + Platform App can coexist in the same nointern workspace. In a "1 Agent = 1 App" model, each agent needs a separate installation.

### Options

**A) Remove workspace_id unique and allow multiple installations**

- Pros: matches original design intent; supports agent-specific BYOA plus Platform coexistence.
- Cons: breaks existing assumption that `get_by_workspace()` returns one row; queries must change.

**B) Keep 1 installation per workspace**

- Pros: simple.
- Cons: agent-specific BYOA impossible; mismatches design intent.

**C) Hybrid: 1 Platform + N BYOA**

- Adds complexity with no real difference from A.

### Decision: A — multi-installation per workspace

**Rationale:**

1. Implements the intended "1 Agent = 1 App" model.
2. Allows one Platform App + N BYOA apps in a workspace.
3. Keep `slack_team_id` unique to prevent the same Slack workspace from being connected to multiple nointern workspaces.

**Schema changes:**

- Remove `uq_slack_installations_workspace_id`.
- Add `uq_slack_installations_workspace_agent`: `(workspace_id, agent_id)` WHERE `mode = 'byoa'`, preventing duplicate BYOA for one agent.
- Add `uq_slack_installations_workspace_platform`: `(workspace_id)` WHERE `mode = 'platform'`, keeping Platform at one per workspace.

## Discussion Point 3: BYOA Credential Storage

### Problem

BYOA event verification needs `signing_secret`, and routing needs `slack_app_id`, but neither exists in DB.

### Options

**A) Add columns to `slack_installations`**

- Add `slack_app_id`, `encrypted_signing_secret`.
- Pros: simple, reuses existing table.
- Cons: null in Platform mode.

**B) Separate `slack_byoa_configs` table**

- Pros: normalized.
- Cons: requires JOIN and adds complexity.

### Decision: A — add columns to existing table

**Rationale:**

1. Same pattern as `agent_id`: only used in BYOA, null in Platform.
2. `encrypted_signing_secret` uses the same `CredentialCipher` as existing `encrypted_bot_token`.
3. Not complex enough to justify a separate table.

**Added columns:**

- `slack_app_id: VARCHAR(32)` — nullable, BYOA only; Slack `api_app_id`, e.g. `A06ABCDE12`.
- `encrypted_signing_secret: TEXT` — nullable, BYOA only.

**Added constraint:**

- `uq_slack_installations_slack_app_id`: unique WHERE `slack_app_id IS NOT NULL`.

## Discussion Point 4: Manifest Generation Method

### Problem

Design document says "manifest.json download button," but it is not implemented.

### Options

**A) Backend API + frontend download button**

- Download JSON file.

**B) Redirect to Slack manifest URL for one-click app creation**

- `https://api.slack.com/apps?new_app=1&manifest_json={url_encoded_json}`.
- Slack app creation page opens with manifest prefilled.

**C) Provide both A + B**

### Decision: C — both Slack one-click link and JSON download

**Rationale:**

1. Slack manifest URL is the best UX, taking users to the app creation page with one click.
2. JSON download is an alternative for users who prefer manual creation.
3. **Do not include `event_subscriptions.request_url` in the manifest** — BYOA event URL is guided after installation because `slack_app_id` is only known after app creation.

**Manifest contents:**

- `display_information`: agent name/description.
- `features.bot_user`: agent name, always_online: true.
- `oauth_config.scopes.bot`: required scopes: chat:write, channels:history, groups:history, im:history, mpim:history, channels:read, groups:read, im:read, users:read.
- `settings.interactivity.is_enabled`: true; interactions URL is also configured separately after installation.
- `settings.socket_mode_enabled`: false.

## Discussion Point 5: SlackConfig Dependency, BYOA-only Operation

### Problem

Current `Config.slack` is created only when all three values exist: `slack_signing_secret`, `slack_client_id`, and `slack_client_secret`. If `Config.slack is None`, the Bolt app is not created and `/slack/v1/events` returns 501. In a BYOA-only environment, Platform credentials are unnecessary, but events cannot be received without a Bolt app.

### Options

**A) Always create Bolt app, regardless of Platform credentials**

- Since `request_verification_enabled=False`, signing_secret is unnecessary.
- Only OAuth endpoints check Platform credentials.

**B) Split SlackConfig into PlatformSlackConfig + ByoaSlackConfig**

- Too complex.

**C) Require Platform credentials for BYOA too**

- Unreasonable constraint.

### Decision: A — always create Bolt app

**Rationale:**

1. With `request_verification_enabled=False`, signing_secret is not practically needed to create Bolt.
2. Remove `Config.slack is None` check from `_get_bolt_handler` and always return Bolt handler.
3. Create Bolt with `signing_secret="not-used"` and `request_verification_enabled=False`.
4. Platform OAuth endpoints still check `Config.slack` existence.
5. BYOA endpoints perform their own verification with per-installation signing secret.

**Impact:**

- `create_bolt_app()`: replace signing_secret parameter with fixed `request_verification_enabled=False`.
- `_get_bolt_handler`: always return handler.
- OAuth endpoints (`/oauth-callback`, `/oauth-url`, `/exchange`): keep `Config.slack` check.

## Discussion Point 6: Development Environment

### Problem

BYOA requires HTTP Events API, so local testing needs ngrok or another tunnel.

### Options

**A) Integrate ngrok into devserver**

- High complexity and environment-dependent.

**B) Provide documentation only**

- Simple; developers can choose their own tool.

**C) Extend Socket Mode to BYOA**

- Requires customers to provide xapp token; unrealistic.

### Decision: B — documentation only

**Rationale:**

1. Day-to-day development is covered well enough by Platform App with Socket Mode.
2. BYOA development testing is infrequent.
3. ngrok/cloudflare tunnel setup differs by developer environment.
4. testenv can test BYOA flow by calling HTTP API directly without real Slack events.

## Discussion Point 7: BYOA Frontend Form Improvement

### Problem

Current form has three fields: bot_token, slack_team_id, slack_team_name. BYOA needs signing_secret and slack_app_id. slack_team_id/slack_team_name can be looked up automatically from bot_token using Slack `auth.test` API.

### Decision: keep three fields but change their meaning

**New form fields:**

1. **Bot Token** (`xoxb-...`) — Bot User OAuth Token from Slack App.
2. **Signing Secret** — copied from Slack App Basic Information.
3. **App ID** — copied from Slack App Basic Information.

**Automatic lookup:**

- When bot_token is entered, call `auth.test` API → fill `slack_team_id`, `slack_team_name` automatically.
- This also validates token validity.

**Post-install guidance:**

- After installation completes, show Event URL and Interactions URL.
- Provide "Copy" buttons.
- Provide link to Slack app settings page.

## Migration provenance

- Historical source filename: `0026-slack-byoa.md`
- Source date basis: `adr.created`
- This ADR was reconstructed as a historical record; no new requester confirmation is implied.
