---
title: "Runtime Browser Selection Design"
created: 2026-10-23
implemented: 2026-10-24
tags: [browser, runtime, architecture, configuration]
document_role: primary
document_type: design
snapshot_id: browser-261023
---

# Runtime Browser Selection Design

- Snapshot: `browser-261023`
- Requirements: [browser-261023/REQ](../requirements/browser-261023-runtime-engine-selection.md)
- Decisions: [browser-261023/ADR](../adr/browser-261023-runtime-engine-selection.md)
- Mode: Collaborative; decision owner: requester.
- Revision: `1`; approved by the requester on 2026-10-23 after presentation of this complete revision and its authority set.

## Current behavior and gap

`RunnerBrowserManager` currently starts Patchright during Runner setup, owns Session-specific persistent contexts and task/page identities, and is directly referenced by the viewer and operation dispatcher. `browser.v1` is advertised only after initialization. Browser settings currently enable/disable admission but do not select an implementation.

The Agent's infrastructure Runtime desired/applied configuration is tied to Provider acknowledgement, Runner generation and exact configuration sequence/digest. That configuration also authorizes non-browser work. An engine-only change must not replace that authority, restart Runner, or use Runtime recreation as a shortcut.

Chromium-specific CDP is used by `BrowserPopupTracker` for early exact popup identity. Public Camoufox page/popup events do not supply equivalent early metadata. ADR-D3 explicitly permits manual viewer popup selection on Camoufox, while preserving popup registration and explicit Agent expectations.

## Design Authority

- Design revision: `1`

| ID | Material mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Per-Agent persisted browser choice in Runtime settings; Patchright default; independent of browser enablement | REQ-1, REQ-2 | required |
| M2 | Both browser implementations packaged in the current Runtime distribution; no browser-image recreation mode | ADR-D1 | decided |
| M3 | Confirmation on changed selection initiates immediate browser-only transition; no shell/Runtime replacement | ADR-D1, ADR-D2, REQ-4 | decided |
| M4 | Separate browser application evidence using exact existing operation/request and current Runner identities, without advancing infrastructure configuration or adding a version counter | REQ-2, REQ-4, ADR-D1, ADR-D2; unchanged Runtime operation fencing | derived |
| M5 | Gate browser admission while switching; retire old sources/tasks before admitting replacement; serialize switching with browser effect execution | REQ-3, REQ-4; current source/operation authority | derived |
| M6 | Backend-specific SDK boundary; existing common commands and viewer/input behavior | REQ-3 | required |
| M7 | Patchright early popup attribution retained; Camoufox popup registration without viewer auto-selection; explicit Agent expectations retained | ADR-D3 | decided |
| M8 | Per-Session and per-backend native state; retain existing Patchright profile path; no state transplant | REQ-5 | required |
| M9 | Explicit failure/unavailability, no silent backend fallback, no implicit Runtime start; observe uncertain application before resubmission | REQ-2, REQ-4, ADR-D2; current uncertain-effect policy | derived |
| M10 | Deterministic contract matrix for both implementations and live Runtime switch with unrelated work retained | REQ-3, REQ-4, REQ-5 | required |

Mechanisms use the existing operation/request identity and Runner generation model. No new monotonic browser revision, protocol-version family, migration-version selector or fallback parser is introduced. Ordinary database migration metadata and pinned package versions are not new product configuration-versioning features.

## State ownership and configuration flow

### Requested selection

The backend's Agent-owned browser setting is the sole durable source of requested implementation. The closed choices are `patchright` and `camoufox`. The existing browser-enabled setting remains independent. Runtime-free or stopped Agents can retain a choice without starting compute or advertising an applied browser.

The public settings mutation uses existing Agent administration authority and an exact expected-current browser intent identity to reject stale settings writes. A changed save creates an opaque operation/request identity, persists the requested choice and queues the corresponding browser application work as one repository-owned transaction. This is an application identity, not a new ordered version counter. An unchanged ready selection is a no-op; an explicit retry of a failed selection is a new application intent.

A durable current application record holds the requested implementation, exact intent identity and bounded failure/result evidence. Applied evidence additionally binds Runtime ID and current Runner generation. Historical browser operations are not a second mutable settings source. Superseded work cannot overwrite current requested/applied state.

### Actual browser

Runner owns the actual browser process and reports implementation, readiness/failure and the exact application identity. Backend reporting accepts that evidence only for the current authorized intent, Runtime and Runner generation. A saved preference or dispatched message alone is not an applied result.

At a minimum, the public projection distinguishes:

- requested choice with no live applicable Runtime;
- applying;
- ready with exact current applied implementation;
- failed/unavailable with a bounded reason and explicit retry path.

Current Runner evidence is not treated as valid after generation replacement, connection expiry or selection supersession.

### Control transport and recovery

Use a closed internal browser-configuration control operation carried by the existing Runner control connection and system-operation authority. It is not a user-facing browser action, shell command, environment variable override, Provider lifecycle operation, or new Agent tool. Its payload contains only supported backend selection and exact current application identity; it cannot name arbitrary executables, profiles or paths.

Server-side delivery revalidates the current durable intent, Agent lifecycle, Runtime binding, Runner generation and expected infrastructure authority before forwarding the operation. Superseded intents are discarded. The ordered control stream and a browser-specific Runner transition coordinator serialize current configuration messages; new intent admission fences old pending browser input before startup effects. The transition coordinator never uses a delayed configuration completion as permission to overwrite a newer intent.

On Runner registration/replacement, the backend schedules/reconciles only the current requested choice. Runner does not expose a browser-ready surface until the current choice has been initialized and acknowledged. Generic process/file capability does not wait for browser readiness. Reconnection observes/reports current browser evidence before considering whether an idempotent configuration application is needed.

A lost response first triggers status reconciliation for the same exact application identity. It does not replay website actions or reset an already-correct browser merely to obtain another acknowledgement. A stale command from a former Runner generation or superseded intent cannot clear current pages or change current state. Durable work-claim and attempt fencing follows existing repository-owned task patterns, independent of optional Redis.

## Browser-only transition

1. Authorize and persist the confirmed changed selection and application work.
2. Mark browser admission unavailable/applying for the old intent. Stop admitting new Agent operations, tab mutations and viewer input under retired intent evidence.
3. In Runner, serialize a browser transition with effect execution. Invalidate the prior manager/task identities before awaiting any cleanup or launch, cancel outstanding browser operations, stop viewer capture sources, release held input best-effort and close old contexts/driver.
4. Do not change the logical Runtime, infrastructure configuration sequence/digest, Runner generation, terminal registries, process registries, file operations or shell environment.
5. Initialize only the selected implementation through its SDK/backend boundary. Bind a fresh manager's resource identities and the current application identity. Initial browser startup creates no public Session tab.
6. Publish ready evidence only after successful initialization. New tabs are independently admitted and receive new task/page/incarnation and viewer attachment identities.
7. On failure, retain requested choice and expose failure; no automatic rollback/fallback. If retiring the old browser cannot be established, stay browser-unavailable rather than start a competing engine or claim success.

All browser operations already in progress may become cancelled or outcome-unknown. Closing a page cannot undo a site submission. The UI and tools must not describe cancellation as rollback or replay the uncertain operation. Closing the browser subsystem does not cancel unrelated shell/process jobs.

## SDK and implementation boundary

Separate SDK-owned lifecycle and popup behavior from common product behavior. Patchright and Playwright objects/errors are distinct Python classes despite similar APIs; catch/translate both at the backend boundary and use explicitly typed structural interfaces for the common surface rather than pretending one concrete SDK type is the other. Do not suppress type errors with `Any`, broad casts or private SDK-object access.

The common manager retains exact task/page/frame/ref identity, operation/interaction guards, downloads and authorized uploads, confidential input, dialogs, capture metadata and source fencing. Backends supply driver initialization, persistent context creation/close, SDK error normalization and any backend-specific popup tracker. Browser viewer, field editing and native input must be exercised against each backend rather than assumed compatible from method names.

Patchright retains current headed/sandbox/proxy behavior. Camoufox uses the documented persistent Playwright Firefox-compatible launcher, the same network authority, and the owned display lifecycle. No stealth header overrides, proxy rotation, automatic external challenge solving, arbitrary add-ons or personal profile attachment are introduced.

### Popups

- Agent-triggered pre-armed `expect=popup` remains common SDK behavior and verifies the resulting exact page scope.
- Both implementations register native popups in the task/page projection, including delayed and noopener pages supported by the SDK.
- Patchright retains its native CDP target/owner lifecycle and current race guards.
- Camoufox supplies no viewer automatic selection hint. No URL matching, event-time owner inference, private protocol calls, or page-world interception substitutes for exact attribution.
- The experimental choice discloses manual selection of popup tabs. Other viewers never receive another attachment's focus preference.

## Profiles and migration

Preserve the existing Patchright Session profile path so current site state remains usable. Camoufox uses a distinct backend-specific Session path derived under the current Runner-reported Agent Workspace. Paths are internal, resolved and symlink-checked; callers cannot override them.

Backend switching closes contexts without deleting either profile. Returning to Patchright or Camoufox reuses only that implementation's own durable native bytes. Existing supported migration/cleanup behavior remains engine-specific; Chromium Singleton marker cleanup is not blindly applied to Firefox. No cookie export, login copying or profile conversion is added.

The database migration initializes existing Agents to Patchright and establishes initial current selection identity without changing the Runtime's physical target. Newly created Agents use the same default. Update ORM, API projections, generated OpenAPI clients and test fixtures together; do not introduce optional legacy field parsing as a substitute for migration.

## UI and authorization

Add the browser choice to the Agent's existing Runtime settings, not the shared Workspace Runtime Profile editor. Only current administrators can mutate it; read-only states remain read-only. Existing browser enablement is not implicitly toggled.

Changed selection opens a confirmation naming the actual effect: all browser tabs and browser operations for this Agent will end; terminal and other Runtime jobs continue. On confirmation, save and initiate application immediately. Show requested versus applied state only when different or unavailable. Camoufox is labeled experimental and identifies manual popup selection; do not promise third-party site access.

When Runtime is offline/missing, show that the saved choice applies on the next valid start. On failure, provide explicit retry/current-state refresh and allow an explicit choice of Patchright. Do not present restoring the default as automatic recovery. Component stories cover confirmation, cancelled change, applying, failed, offline and permission boundaries, including stale mutation rejection.

## Packaging and operational limits

Install both browser families in the same image as accepted by ADR-D1. Dependency changes go through the package manager. Pin and verify a compatible Camoufox Python/browser pair and download integrity at build time, following upstream's stamped browser pairing rather than fetching whatever browser release is newest at Runtime startup. Record package, browser and Playwright-driver versions in build evidence.

The feasibility probe used Camoufox Python 0.5.8, its stamped v156.0.1-beta.36 browser and Playwright 1.62.0; this pairing is not automatically a production security approval. Check the selected pair's known compatibility/security findings and actual image startup. A failing pair is a release blocker, not grounds to bypass the upstream protocol guard or silently downgrade the default browser.

Account for additional binary/dependency size in actual image build output. The latest inspected browser prerelease archive is approximately 1.3 GB compressed; that is not an exact estimate for the selected build or final image delta. Do not add image selection/recreation or download-at-first-use as an undisclosed optimization. These belong to a later snapshot if needed.

Logs use bounded engine/state/reason labels and exact non-secret request identities. Do not log page contents, cookies, credentials or sensitive URLs as diagnostics. Startup failure preserves independent Runner capabilities; no operational deployment/restart is performed by this feature-development task.

## Failure and compatibility matrix

| Condition | Required behavior |
| --- | --- |
| Camoufox not installed/invalid pair | Browser unavailable with explicit reason; no Patchright fallback |
| No live Runtime | Save choice, no compute allocation; not applied |
| Different choice while a website action is pending | Confirmed browser transition retires browser authority; original website outcome remains unknown where appropriate |
| New choice supersedes old queued work | Reject old intent before effects; old completion cannot promote applied evidence |
| Runner replaced/reconnected | Fence previous generation; reconcile only current requested intent before admitting browser work |
| Cleanup fails | Remain browser-unavailable, do not launch competing backend or terminate unrelated Runtime |
| Old page/attachment sends input after switch | Reject before native input; no automatic replay |
| Two administrators save concurrently | Exact-current intent check rejects stale mutation |
| Camoufox viewer popup | Register tab, no automatic tab selection |
| Agent explicit popup expectation | Verify and return exact scoped new page for either backend |
| Image/SDK incompatibility | Fail build/acceptance rather than use fallback or unpaired version silently |

## Removal and Replacement

| Existing unit/behavior | Removal authority | Replacement/remaining authority | Boundary | Absence verification |
| --- | --- | --- | --- | --- |
| Unconditional single-SDK construction in Runner setup | REQ-1, REQ-3, ADR-D1 | Selected backend behind common manager/controller | New image/Runner support | No hardwired sole-backend startup outside backend factory; both contract cases exercised |
| Readiness inferred once from pre-registration default browser initialization | REQ-2, REQ-4, M4/M5 | Current-intent/current-Runner browser application evidence | Registration, reconnect and switch | Wrong-engine ready admission test fails closed |
| Concrete Patchright types/errors leaking across common manager/viewer | REQ-3 | Common typed surface and SDK translation | Backend refactor | Typecheck plus both native SDK acceptance cases |
| Unconditional Chromium popup tracker construction | ADR-D3 | Patchright native tracker; Camoufox no selection hint | Viewer source startup | Camoufox never calls `new_cdp_session`; Patchright tests unchanged |
| Default-only Runtime settings projection/fixtures | REQ-1, REQ-2 | Closed choice and requested/applied projection | API/UI rollout | OpenAPI regeneration and locale/story/test alignment |
| Existing native profile paths and bytes | None: retained | REQ-5 | All switches and migration | Existing Patchright cookie sentinel survives; no cross-engine cookie sentinel |

No current browser tool, Runtime infrastructure configuration authority, unrelated execution backend, profile bytes or default Patchright mode is removed.

## Test Strategy

### Primary E2E flow

One deterministic product E2E uses existing Runtime/testenv fixtures: open a
Patchright page, select Camoufox once, observe retired tabs, open the same synthetic
page through the new engine, and confirm the existing shell/job and Runtime/Runner
identity continue. Do not accumulate restart, round-trip profile, stale-input,
error-state or UI permutations inside this flow. The requester confirmed this
minimal E2E scope on 2026-10-23; implementation mechanisms remain unchanged.

### Test layers and prerequisites

- Runner unit/SDK tests own native profile isolation and return, browser-only resource retirement, stale targets/sources, late work, cleanup/startup failure, unchanged-choice idempotence and cancellation. Both backends exercise dialogs, expectations, files, capture, confidential input and editing contracts. Existing direct Patchright attribution tests stay scoped to that backend; Camoufox registers popups without automatic selection.
- Backend repository/service/transport tests own requested-selection persistence, concurrent/stale intent checks, exact Runner/applied evidence, offline/unsupported behavior, task claims, reconnect/lost-result reconciliation and lifecycle cleanup. Browser-disabled and Runtime-free behavior remains covered at its existing layer.
- Frontend Storybook component tests own settings choices, disclosures, confirmation/cancellation and state/permission rendering; they do not need external APIs.
- Product E2E crosses actual API, Worker/control, Runner and Browser viewer surfaces. Extend existing local fixture pages and Runtime fixtures, not a legacy external-site setup script.
- Both browser binaries and compatible SDK dependencies must exist in the CI Runner image. No Naver account or external CAPTCHA is needed. Missing required local browser prerequisites fail acceptance rather than skip it.
- Optional live-site checks are separate, explicitly requested and reported independently. Third-party site access is not required CI and cannot substitute for protocol/security tests.
- Regenerate API clients with the project skill after API changes. Run Python Ruff/typecheck/pytest for changed subprojects, TypeScript format/lint/typecheck/component tests, image build smoke and final pushed-SHA ordinary CI.

### Evidence

Record exact source SHA, package/browser versions and hashes, deterministic fixture outputs, switch requested/applied evidence, before/after Runtime/Runner identity and continuing-shell marker, JUnit/log locations and content-free screenshots. Exclude credentials, personal browser data and operational URLs. Ship no research profiles, binary archives or temporary probe scripts in the feature diff.

## Feasibility and authority validation

- REQ-1/REQ-2: feasible within existing Agent administration/Runtime settings and typed API generation boundaries; new setting/projection and migration required.
- REQ-3: common SDK surface is feasible in local synthetic probes: input, frames/open shadow, held pointer, explicit popup, prompt, upload/download, wheel/capture and cookie operations passed both SDKs. Full product acceptance remains required. The early-popup gap is resolved at the product boundary by accepted ADR-D3, not an unsafe tracker substitute.
- REQ-4: conditional on implementing and proving the exact-intent/current-Runner transition coordinator and early admission gate. Existing manager close and viewer cleanup can retire browser resources independently; current Runner's process/terminal state is separately owned. This is an explicit implementation/release gate, not an assertion that switching already exists.
- REQ-5: feasible using separate Session/backend profile directories while preserving the existing default path; persistence/isolation acceptance remains mandatory.
- Packaged browser/SDK compatibility, security review and real image size/startup are mandatory release gates. No current evidence authorizes an arbitrary unpaired latest browser.

Every material mechanism has authority in the table. No backend can relax the current browser security contract except the explicitly approved viewer-selection difference. A discovered contract change, inability to preserve unrelated work, required new versioning scheme, unsupported private SDK dependency or unacceptable browser pairing returns to requester decision before implementation proceeds with that mechanism.

## Design Approval

- Mode: Collaborative
- Decision owner: Requester
- Approved on: `2026-10-23`
- Approved Design revision: `1`
- Approved authority IDs: `M1, M2, M3, M4, M5, M6, M7, M8, M9, M10`
- Material scope: optional per-Agent browser selection; confirmed immediate browser-only switch with exact current-intent/Runner fencing; shared current distribution; separated native state; unchanged common tool/security behavior except approved Camoufox manual viewer popup selection.

After the complete revision 1 and M1-M10 approval brief were presented, the requester explicitly reaffirmed proceeding through PR on 2026-10-23. This approval follows that presentation and does not infer approval from an earlier isolated decision. Mark implementation complete only after verified delivery; material scope changes still require renewed authority.
