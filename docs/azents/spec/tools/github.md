---
title: "GitHub connections and identity"
created: 2026-11-04
tags: [wiki]
---

# GitHub connections and identity

Owns GitHub connection setup, personal account authority, installation selection and platform App resolution. The namespace/discovery mechanics used by tools are defined separately.

[Wiki index](../index.md) · [Maintenance](../AGENTS.md)

## Connections

- [Toolkits](../domain/toolkit.md)
- [System Settings](../domain/system-settings.md)
- [Tool discovery and working sets](discovery.md)
- [Runtime tool execution and network authority](runtime-execution.md)

## GitHub New-Connection Wizard

New GitHub creation, in the shared full-page form and exact Agent editor, uses
one progressive surface: execution identity, applicable method, connection
evidence, feature groups, Runtime opt-in, and final review. Earlier sections
remain visible. Personal identity maps to PAT or App user-account modes; App
identity maps to installation modes. Toolkit ownership is the entry context,
not a consequence of identity selection. Saved Toolkit editing retains its
existing controls and authorization behavior.

The creation surface uses numbered section panes, explicit selected/check states,
feature-choice tiles and a compact final settings summary. Explicit identity,
method and next-section gestures move focus and scroll to the revealed heading
in the actual page or nested editor scroll container; ordinary edits, query
refreshes and initial mounting do not trigger progression scrolling. Reduced
motion preferences are respected. A sole available method is selected only
from successful availability evidence; a sole synchronized installation may be
selected automatically without repeating an explicit deselection. Neither
selection starts provider authorization, acknowledges Runtime risk, or publishes.

Self-managed App setup links to the localized `/github-app-guide` page in a new
tab. The read-only guide describes user-account versus installation execution,
the GitHub registration menus, callback/settings choices, least-privilege
feature-specific permissions, credential locations and installation IDs in one
ordered registration flow. It has no preliminary identity-confirmation section.
The callback URL is recommended during registration and marked required for
personal-account OAuth, optional for installation-only execution. Personal App
instructions match the existing non-expiring-user-token contract. The guide
contains no credential inputs and carries no setup secrets or attempt IDs in
its URL. Registration, installation, account authorization and final Toolkit
publication remain distinct actions; the guide documents API/token limitations
rather than promising that all feature groups work with every credential mode.

Management setup availability retains the redacted registration presence field
and adds per-mode local readiness. Loading or query failure is distinct from
confirmed absence/incompleteness. A locally unavailable Platform method is
omitted. Its display name is fetched through the authenticated GitHub SDK App
operation using the current registration; the numeric App ID must match.
Metadata failure shows retry rather than a fabricated name or App absence.
There is no retained display-name configuration/cache or refresh actor.

GitHub-specific setup verification accepts strict PAT or installation-mode
inputs under shared/exact-Agent management authority. It verifies the actual
GitHub user or App and each selected installation, separates target observations
from MCP connectivity, and repeats management admission after provider I/O.
Platform verification additionally reuses the existing current-user/current-App
synced selected-installation authority before metadata, before probe-token
issuance and before returning. Foreign or removed initial targets cause no
provider/probe I/O; authority loss during observation blocks issuance/response.
Denied targets contain no invented owner metadata. Generic MCP connection-test
contracts remain unchanged. Setup verification publishes no Toolkit and creates
no durable credential receipt; final ordinary PAT/installation creation retains
its existing credential and Platform binding authority.

User-account App setup returns in the same browser context to the same Wizard.
The existing exact encrypted candidate remains unpublished while the manager
chooses feature groups, optional Runtime token injection and final metadata.
App display metadata for a candidate is read through an exact-attempt endpoint
with live scope/registration checks before and after the provider call.
Only nonsecret attempt context is Session-stored. Downstream edits are in memory,
not autosaved; reload restores the server's initial defaults for another review.

Final review shows the actual execution identity/App, ownership/sharing context
and the selected settings. All supported feature groups remain configurable;
feature exposure does not grant GitHub access. Runtime injection is OFF by
default and ON requires exposure acknowledgment. Only the final action creates
the Toolkit. Both identity branches provide reset, which invalidates dependent
connection evidence, and the host close action abandons unpublished setup.
There is no duplicate final cancel button. Explicit abandonment invalidates
local operations; a late connect response cancels its exact attempt rather than
redirecting. Intentional same-context OAuth navigation does not cancel on unmount.

New-creation close/reset is restricted while final publication is pending,
separately from candidate review and existing saved-edit/attachment guards.
An uncertain write outcome is not automatically replayed or reported as a
rollback; the UI provides saved-state inspection. Closing/resetting does not
disconnect a saved Toolkit, uninstall an App, or prove provider revocation.

## GitHub User Account Authority

GitHub has five explicit authentication modes: `pat`, BYOA installation
`github_app`, Platform installation `github_app_platform`, BYOA user account
`github_app_user`, and Platform user account `github_app_platform_user`. Existing
installation and PAT credentials are not converted. Public setup availability
is management-authorized and reports the Platform registration as absent,
incomplete, or configured without exposing its credentials. The form omits
unavailable Platform options while retaining PAT and BYOA.

A user-account connection belongs to the Toolkit, not the current participant.
Workspace-shared managers and the exact Agent's authorized administrators use
their existing management boundaries to connect it. Authorized participants,
including other Workspace members, execute under that saved account without
connecting their own GitHub account. Connection creates no new participation
authority. The form and confirmation identify the account, selected App/source
and Agent-only or Workspace-shared scope, including use by existing automatic
execution and ordinary conversation disclosure.

New user-account Toolkit creation authorizes before publication. The shared and
Agent-owned `github-user-creations` routes retain submitted settings/registration
and a reviewed candidate in a separate encrypted ten-minute creation attempt,
never in a saved draft Toolkit. Ordinary create rejects the two user-account
modes with authorization guidance; PAT and installation creation are unchanged.
Connect, exchange, review, cancel and confirm revalidate the exact active manager,
Auth Session, Workspace, optional Agent, App/source and callback. Confirmation
creates ToolkitConfig, its connected account and the Agent-owned namespace
reservation in one database-only transaction. Failed confirmation rolls back all
publication; cancellation, rejected exchange and expired/abandoned attempts
expose no new Toolkit to lists, attachments or execution.

New-creation confirmation requires the exact attempt ID and a complete strict
final-settings DTO. Name/slug/defaults, supported metadata, feature groups,
timeout, enabled/tool exposure and Runtime choice are validated and overlaid on
the exact locked candidate. Authentication mode, App/source/client identity,
credentials, callback and owner are never accepted as final-setting changes.
Runtime ON requires acknowledgment, which is not persisted as credential
authority. The transaction repeats live scope, REVIEW/expiry and current binding
checks, then atomically creates the Toolkit/account/Agent namespace and consumes
the attempt. Correctable input failure preserves a still-live candidate. There
is no attempt-settings update API, create-then-update publication, or creation
attempt-ID-only fallback. Existing saved-Toolkit reconnect confirmation remains
unchanged.

Existing Toolkit setup reserves a ten-minute, one-use attempt bound to the exact active Azents
User/Auth Session, Workspace, Toolkit, owning Agent when applicable, callback,
registration and current connection. It verifies the App/client binding before
issuing a PKCE S256 authorization URL with random state. GitHub authorization
and App installation are separate provider actions; opening an installation or
request link is not an approval/request-submission claim. Callback exchanges the
code and verifies `/user`, then stages an encrypted candidate. An explicit
account-and-sharing confirmation alone activates it. Cancellation, callback
failure and unconfirmed replacement preserve the saved account.

Only GitHub App user tokens without scheduled expiration are accepted. The App
must opt out of expiring user-to-server tokens; expiring/refresh envelopes are
rejected with configuration guidance. There is no token refresh actor. Saved
connection and candidate/setup payloads are encrypted at rest. Public status,
review and access DTOs expose allowlisted identity/readiness only, not
credentials. Existing Toolkit authorization reserves a popup before asynchronous
preparation; callbacks notify only the exact same-origin opener with attempt
identity and automatically return to the originating Details/Edit surface.
New creation uses the same browser context and restores the originating shared
form or Agent configuration modal. Only nonsecret scope/attempt identity is
persisted in browser Session storage; review is reread from the server and account
and sharing confirmation remains explicit. Callback code/state are removed from
the URL, and credentials are never posted to the opener or browser persistence.
Same-registration edits retain the saved account; blank write-only registration
fields preserve existing values, including untouched Platform-user forms.
Visible source names consistently distinguish self-managed and platform-provided
GitHub Apps in every supported locale.

Access observations paginate App installations and their repositories for the
connected user. Personal and multiple organization owners remain independently
usable. Missing/denied/SSO targets have bounded failure observations and recheck
or GitHub handoff actions, not an exclusive selected organization or an Azents
repository allowlist. GitHub enforces the intersection of user permission, App
permission and repository policy. A target-specific 403 or 404 does not
invalidate the whole account.

Worker admission resolves the current Toolkit/Workspace/Agent/AgentSession and
shared attachment or Agent ownership. Disabled/detached/foreign contexts, missing
connections and changed App/source/client identity fail closed. Platform App
credentials resolve from current System Settings; same-identity key/secret
rotation remains distinct from App replacement. Every MCP discovery and call,
including a retained tool-snapshot handler, resolves the current connection
immediately before provider I/O. Tool schemas may be cached; user credentials
are not installation-token TTL cached. Definitive HTTP 401 is observed at
the MCP transport boundary before SDK normalization and conditionally marks only
the admitted connection ID `reconnect_required`. A late failure cannot mark a
replacement connection. Authentication failure does not reissue credentials,
substitute PAT/installation/another account authority, or replay an uncertain
mutation result. Existing bounded HTTP 429 transport handling remains unchanged.

Runtime integration is opt-in and off by default. New command dispatch resolves
the current user token for `GH_TOKEN` and `GITHUB_TOKEN` under the existing
environment merge/disclosure contract, with no installation map or default
installation selector. Disconnect/replacement blocks later resolution or supplies
the new token; an already-admitted request, running process, terminal environment
or copied token cannot be recalled.

Disconnect, confirmed replacement, cancelled/rejected candidates, authentication
mode changes and Toolkit/Agent deletion capture exact token/App cleanup facts.
After local repository completion, orchestration awaits a bounded exact-token
GitHub revocation attempt outside the transaction. Expected provider, timeout
or current-registration failures produce sanitized warnings and do not undo or
block local completion. No cleanup state, proof probe, retry API/UI or deletion
barrier is retained. Local success is not proof of GitHub revocation: a provider
failure may leave a copied non-expiring token valid. Cancellation and unexpected
defects remain visible. Disconnect neither uninstalls the App nor erases earlier
external writes or conversation content; detaching one shared attachment does
not disconnect other Agents.

Credential-free required E2E exercises Platform/BYOA setup, staged activation,
another participant's MCP actions across personal/two-org targets, denied-target
isolation, replacement, exact 401 publication, fail-open cleanup and new Runtime
opt-in/off/on/replacement command injection. The testenv-only SDK/MCP/browser
fixture is enabled only by explicit testenv configuration; normal deployments
continue using GitHub endpoints and no synthetic credentials or provider
registration changes are required.

## GitHub Multi-Installation Routing

GitHub App Toolkit credentials are installation-aware.

- `github_app` stores App ID, private key, and `installations[]` target metadata.
- `github_app_platform` stores `installations[]` target metadata plus the durable Platform App ID that authorized them. It resolves the current effective App credentials from System Settings at each OAuth or token operation boundary.
- Each installation target includes `installation_id`, `account_login`, `account_type`, and optional avatar URL.
- Platform App credentials validate every selected installation through the current user's synced `github_user_installations` access list.

At runtime, GitHubToolkitProvider creates one lazy MCP binding per installation. `update_context()` collects each binding's GitHub MCP tools and prefixes them with a safe account-login segment before the engine applies the ToolkitConfig slug prefix. For example, a toolkit slug `github` with `azents` and `hardtack` installations exposes final tool names such as `github__azents__get_file_contents` and `github__hardtack__create_pull_request`. The toolkit prompt includes the account-login to installation-ID mapping so the model can choose tools by repository owner.

When Runtime environment injection is enabled, multi-installation GitHub App credentials expose `GITHUB_INSTALLATION_MAP` and installation-specific token variables. The git credential helper routes HTTPS Git credentials by repository owner. GitHub CLI commands use `GH_TOKEN` / `GITHUB_TOKEN` from the current default installation. The default installation initially falls back to the first configured installation and can be changed during the session with the `switch_installation` tool by passing an installation ID or account login. The selected installation is stored in session-bound Toolkit State under namespace `github` and state name `selected_installation`. Single-installation credentials also expose `GH_TOKEN` and `GITHUB_TOKEN` for normal GitHub CLI compatibility.

## Platform GitHub App identity and runtime resolution

Platform App installation rows and `github_app_platform` Toolkit credentials are bound to the numeric App ID that authorized them. The App ID is mandatory for every persisted record. OAuth synchronization writes App-aware installation ownership. Toolkit create, update, and unsaved connection-test paths derive the App ID from the current server-resolved Platform App snapshot rather than accepting a client-selected identity. The application does not normalize retired unbound records at startup.

Public install URL generation, OAuth start/callback, installation synchronization, and Worker token issuance resolve one coherent Platform GitHub App snapshot from System Settings at the operation boundary. OAuth state carries the internal effective generation, and callback processing rejects generation drift before code exchange. Token issuance verifies the Toolkit's bound App ID and the User installation's App ID against the current effective App before any external token request. Same-App key or OAuth-secret rotation preserves the binding; an App-ID mismatch fails closed.

Workspace installation synchronization runs through a session-free service:
exchange and list HTTP precede one completed, ordered User/App upsert/prune
transaction. That final operation repeats the existing active User/exact Auth
Session, immutable admitted Workspace, current membership, and `TOOLKITS_WRITE`
conditions. The captured App identity remains the synchronization scope; no
second Platform generation fence is added. Temporary-token revocation occurs
only after successful Workspace synchronization, while Agent setup retains its
existing `finally` revocation. Persistence keeps duplicate-row order and defaults
a missing or non-string avatar to an empty string; the Public list separately
requires a string avatar.

GitHub App identity, App/user installation listing, installation-token issuance,
OAuth authorization-code exchange and temporary-token revocation use public
asynchronous GitHubKit operations. SDK transport retains the current endpoints,
authentication, `2022-11-28` header, five-second timeout and first-page
100-installation limit; retries and response caching are disabled. App JWT
issuance retains RS256, normalized PEM newlines, a 60-second backdate and a
nine-minute expiry.

Installation/account JSON is decoded at provider ingress into immutable
`GitHubInstallationSnapshot` records. Domain, persistence and Public projections
consume declared fields while preserving ordered duplicates, boolean-ID
compatibility, malformed-record skipping, and the distinction between unknown
avatars and explicit empty strings. Persistence retains its empty-string
fallback; Public projections omit unknown avatars. Provider extensions remain
compatible, and no Public wire field is added or renamed.

Expected HTTP errors retain the caller contract. Revocation handles expected
HTTP cleanup failures once; unexpected defects and cancellation propagate.
Validation diagnostics do not expose token-bearing provider payloads.

Toolkit list/detail responses expose an optional redacted `authorization_state` with `status=reconnect_required` and the stable reason `app_identity_changed` when a persisted Toolkit belongs to a different Platform App. Main Web uses this Public API projection to block misleading connect/test actions and guide a manager to reconnect; it does not call the Admin API or depend on the Admin client. Persisted Toolkit configuration and Agent attachments are retained across App identity changes.

## References

Selected source entrypoints, not an exhaustive dependency map. Verify the relevant
claim through current callers, models and tests.

- [`python/apps/azents/src/azents/services/toolkit`](../../../../python/apps/azents/src/azents/services/toolkit)
- [`python/apps/azents/src/azents/core/github_system_setting.py`](../../../../python/apps/azents/src/azents/core/github_system_setting.py)
