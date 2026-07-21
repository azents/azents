---
title: "Unified Email Authentication Design"
tags: [backend, api, frontend, historical-reconstruction]
created: 2026-02-17
updated: 2026-02-19
implemented: 2026-02-19
document_role: primary
document_type: design
snapshot_id: email-260217
migration_source: "docs/azents/design/email-login-onboarding.md"
historical_reconstruction: true
---

# Unified Email Authentication Design

## Overview

Unify login and signup with a single email authentication flow. Based on global User model, one login grants access to all workspaces.

### Authentication Flow

```mermaid
graph TD
    Landing["Landing page"]
    Landing -->|Login| EmailInput["Email input"]
    EmailInput --> CodeVerify["Verification code check"]
    CodeVerify -->|"JWT issued (global)"| Hub["Workspace list"]
    Hub -->|Select| WSDash["Workspace dashboard"]
    Hub -->|Create new| CreateWS["Workspace creation"]
    CreateWS --> WSDash

    WSDash2["Direct workspace URL access<br/>(/w/{handle})"]
    WSDash2 -->|Unauthenticated| LoginPage["Redirect to /login"]
    LoginPage --> EmailInput
```

### Key Changes (compared to previous)

| Item | Previous | Change |
|------|------|------|
| User model | Independent per Workspace (WorkspaceUserIdentity) | global User + workspace membership |
| Token system | email_token + workspace_token (2 steps) | single access_token (global) |
| Login flow | email verification → workspace selection → workspace login | email verification → issue JWT immediately |
| Cookies | `ni-email-token`, `ni-ws-token`, `ni-ws-refresh` (3) | `ni-token`, `ni-refresh` (2) |

## JWT Token System

### Access Token

| Item | Content |
|------|------|
| **Purpose** | All API access (global) |
| **Issued when** | email verification code succeeds, token refresh |
| **Expiration** | 30 minutes |

**JWT Payload:**
```json
{
  "sub": "<user_id>",
  "sid": "<session_id>",
  "exp": "<timestamp>",
  "iat": "<timestamp>"
}
```

### Refresh Token

| Item | Content |
|------|------|
| **Purpose** | Refresh Access Token |
| **Issued when** | authentication succeeds, token refresh |
| **Expiration** | 180 days |

## Backend API Design

### Auth API (`/auth/v1/`)

#### 1. Send email verification code
```
POST /auth/v1/email/send-code
Body: { email: string }
Response: { csrf_token: string }
```

#### 2. Verify email verification code
```
POST /auth/v1/email/verify
Body: { email: string, code: string, csrf_token: string }
Response: { access_token: string, refresh_token: string, expires_in: number }
```
- If new email, automatically create User.
- If existing email, log in as existing User.
- Create Session and issue JWT.

#### 3. Refresh token
```
POST /auth/v1/token/refresh
Body: { refresh_token: string }
Response: { access_token: string, refresh_token: string, expires_in: number }
```

#### 4. Logout
```
POST /auth/v1/logout
Headers: Authorization: Bearer <access_token>
Response: 204
```

### Workspace API (`/workspace/v1/`)

#### List workspaces (auth required)
```
GET /workspace/v1/workspaces
Headers: Authorization: Bearer <access_token>
Response: { items: [...], total: number }
```
- Extract user_id from access_token.
- Query all workspaces where that User participates as WorkspaceUser.

#### Create workspace (auth required)
```
POST /workspace/v1/workspaces
Headers: Authorization: Bearer <access_token>
Body: { workspace_name, workspace_handle, owner_name, locale? }
Response: { workspace_handle: string }
```
- Create workspace + automatically register creator as Owner.

#### Get workspace (public)
```
GET /workspace/v1/workspaces/{handle}
Response: { name: string, handle: string }
```

## Frontend Routing Design

### Route Structure

| Path | Page | Auth |
|------|--------|------|
| `/` | landing page | none |
| `/login` | email input | none |
| `/login/verify` | verification code input | none |
| `/workspaces` | workspace list | access_token required |
| `/workspaces/create` | workspace creation form | access_token required |
| `/w/{handle}` | workspace dashboard | access_token required |

### Auth Guard

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant Page as Auth-required page
    participant LoginPage as /login

    User->>Browser: Access page
    Browser->>Page: Load page
    Page->>Page: Check ni-token cookie
    alt no token or expired
        Page->>LoginPage: redirect
        LoginPage->>User: show email input form
    else token valid
        Page->>User: show content
    end
```

### Token Storage

| Token | Storage location | Cookie key | maxAge |
|------|-----------|---------|--------|
| access_token | httpOnly cookie (server-side) | `ni-token` | none (session) |
| refresh_token | httpOnly cookie (server-side) | `ni-refresh` | 30 days |
| expiration time | httpOnly cookie (server-side) | `ni-token-expires-at` | none (session) |

All tokens are managed by server as **httpOnly cookies**. Request interceptor in tRPC context checks token expiration before each API call and refreshes automatically when needed. Cookie setting is handled by Set-Cookie header through tRPC `resHeaders`.

## Authentication Sequence Diagrams

### Login (new user)

```mermaid
sequenceDiagram
    participant User
    participant Web as nointern-web
    participant tRPC as tRPC Server
    participant API as nointern API
    participant DB as PostgreSQL

    User->>Web: Access /login
    Web->>User: Email input form

    User->>tRPC: auth.sendCode({ email })
    tRPC->>API: POST /auth/v1/email/send-code
    API->>DB: Create EmailVerification
    API->>API: Send email
    API-->>tRPC: { csrf_token }
    tRPC-->>Web: redirect /login/verify

    User->>tRPC: auth.verify({ email, code, csrfToken })
    tRPC->>API: POST /auth/v1/email/verify
    API->>DB: Check EmailVerification
    API->>DB: Create User (new)
    API->>DB: Create UserEmail
    API->>DB: Create Session
    API->>API: Create JWT
    API-->>tRPC: { access_token, refresh_token }
    tRPC->>tRPC: set ni-token, ni-refresh cookies
    tRPC-->>Web: redirect /workspaces

    User->>Web: Access /workspaces
    Web->>tRPC: workspace.list()
    tRPC->>API: GET /workspace/v1/workspaces (Bearer token)
    API-->>tRPC: workspace list (empty array)
    tRPC-->>Web: no workspace → prompt creation
```

### Login (existing user)

```mermaid
sequenceDiagram
    participant User
    participant tRPC as tRPC Server
    participant API as nointern API
    participant DB as PostgreSQL

    User->>tRPC: auth.verify({ email, code, csrfToken })
    tRPC->>API: POST /auth/v1/email/verify
    API->>DB: Check EmailVerification
    API->>DB: Lookup User (existing)
    API->>DB: Create Session
    API-->>tRPC: { access_token, refresh_token }
    tRPC->>tRPC: Set cookies
    tRPC-->>User: redirect /workspaces

    Note over User: If workspaces already exist, they appear in list
```

## Implementation Files

### Backend

```
python/apps/nointern/src/nointern/
├── rdb/models/
│   ├── global_user.py           # RDBUser model
│   ├── user_email.py            # RDBUserEmail model
│   └── email_verification.py    # RDBEmailVerification model
├── repos/
│   ├── global_user/             # User CRUD
│   ├── user_email/              # UserEmail CRUD
│   └── email_verification/      # EmailVerification management
├── services/auth/               # Unified AuthService (send_code, verify, refresh, logout)
├── core/auth/
│   ├── jwt.py                   # JWT create/verify (sub=user_id, sid=session_id)
│   └── deps.py                  # CurrentUser, WorkspaceMember dependency
└── api/public/auth/v1/          # Public auth endpoints
```

### Frontend

```
typescript/apps/nointern-web/src/
├── shared/lib/
│   ├── cookies.ts               # cookie utilities (read/write, expiration check, Set-Cookie builder)
│   └── getInitialAuthState.ts   # server-side auth state check
├── trpc/
│   ├── context.ts               # Request interceptor, proactive token refresh
│   └── routers/
│       ├── auth.ts              # sendCode, verify, refreshToken, logout
│       └── workspace.ts         # list, create
├── features/
│   ├── auth/                    # login/verification code check
│   └── workspaces/              # workspace list/create
└── app/
    ├── login/page.tsx
    ├── login/verify/page.tsx
    ├── workspaces/page.tsx
    └── workspaces/create/page.tsx
```
