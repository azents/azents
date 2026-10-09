---
title: "GitHub Toolkit Authorization Journey Requirements"
created: 2026-10-09
implemented: 2026-10-09
document_role: primary
document_type: requirements
snapshot_id: github-261009
tags: [github, toolkit, oauth, frontend, security]
---

# GitHub Toolkit Authorization Journey Requirements

- Snapshot: `github-261009`
- Document reference: `github-261009/REQ`

## Problem

A manager completing GitHub authorization encounters a result page asking them to find the original window manually. New user-account Toolkits are already saved before that authorization completes. An unchanged saved Platform-user registration is incorrectly treated as edited, and visible App-source names differ across authentication choices and details.

## Primary Context

### Primary Actor

An existing Workspace Toolkit manager or administrator of the exact owning Agent.

### Primary Scenario

The manager configures a new GitHub user-account Toolkit, authorizes the GitHub account, returns automatically to account/sharing confirmation, and saves a usable connected Toolkit. Later ordinary edits retain that same authorization without repeating account setup.

## Supporting Scenarios

- Mobile users return to an actionable confirmation surface without finding another tab.
- Managers can cancel or fail authorization without leaving a newly saved unusable Toolkit.
- Managers distinguish a self-managed App from a platform-provided App and installation authority from user-account authority.

## Goals

- Complete creation as one coherent authorized-save journey.
- Preserve existing authorization on unchanged-identity edits.
- Make navigation and terminology consistent.

## Non-Goals

- Automatic confirmation of account sharing or authorization under another identity.
- Expiring user credentials, renewal, token caches, global credential hubs or new participation authority.
- New App registrations, live provider mutations, infrastructure changes or deployment approval.
- Changes to unrelated OAuth or existing PAT/installation behavior.

## Requirements

### REQ-1. Automatic actionable return

After successful GitHub authorization, the user is automatically taken to the originating Toolkit account-confirmation surface.

**Acceptance criteria**

- Desktop and mobile flows do not require manual original-tab discovery.
- The returned surface loads the exact server-reviewed candidate and its sharing scope.
- Review still requires explicit confirmation; a redirect does not activate credentials.
- A failed or expired callback reports useful recovery without redirecting to an unrelated account/Toolkit.

### REQ-2. Authorize before new saved Toolkit completion

A new user-account Toolkit is not completed as a saved Toolkit before its account authorization and explicit account/sharing confirmation succeed.

**Acceptance criteria**

- Newly completed saved Toolkits have a connected verified account, not merely registration credentials.
- Cancelling, denying, failing or abandoning creation does not expose a newly saved unauthenticated Toolkit in normal lists or Agent execution.
- A successful creation publishes its account and selected Toolkit configuration together.
- Failure preserves existing Toolkits and their connections.

### REQ-3. Existing authorization inheritance on edit

Ordinary edits of the same Toolkit keep its saved authorization rather than requiring new setup.

**Acceptance criteria**

- Name, description, tools, Runtime opt-in and other non-identity edits preserve the saved account/connection.
- Empty write-only registration fields mean retention, not lost credentials.
- Unchanged Platform-user registration does not show a false registration-change/reconnect requirement.
- Actual account, authentication source, App or OAuth-client identity changes remain explicit and fail-closed; no unrelated credential is inherited.

### REQ-4. Consistent source terminology

Every visible source label uses one coherent name per locale across mode choices, help and connection details.

**Acceptance criteria**

- No mixed `BYOA`, `Your own App` and other names for the same source in normal UI.
- Installation and user-account authority remain distinguishable.
- English, Korean, Japanese and French labels and help retain their natural meaning and aligned message keys.

## Fixed Constraints

- Exact current Workspace/Agent/Toolkit/User/Auth Session/App/callback admission and one-use PKCE/state remain fail-closed.
- Existing Toolkit ownership, participant delegation and staged account/sharing confirmation remain unchanged.
- Exact-token cleanup remains bounded awaited fail-open with sanitized expected failure logging, without retained cleanup/retry/proof state or deletion barriers.
- Tokens, App secrets and OAuth code/state are not exposed in public projections, return URLs or browser-persisted configuration.
- The implemented `github-261008` snapshot remains immutable; current behavior changes belong to this snapshot and Living Specs.

## Open Assumptions

- The requested authorization-before-save outcome applies to new GitHub App user-account Toolkits; PAT and installation mode creation retain their existing contracts.
- Existing saved but disconnected Toolkits remain available for explicit reauthorization; they are not silently deleted or converted.

## Confirmation

The requester confirmed the complete REQ-1..4 statement and the bounded UI/API authorization-before-create brief on 2026-10-09, then explicitly instructed immediate implementation. PAT and installation authority creation remain unchanged. New user-account creation must not publish an unauthenticated Toolkit; ordinary edits inherit the existing account. No saved-draft Toolkit lifecycle is authorized.
