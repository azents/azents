---
title: "Browser Native Input and Paste Design"
created: 2026-10-16
implemented: 2026-10-16
document_role: primary
document_type: design
snapshot_id: browserinput-261016
tags: [browser, frontend, runtime]
---

# Browser Native Input and Paste Design

Scope: [browserinput-261016/REQ](../requirements/browserinput-261016-native-input-and-paste.md), with [browserinput-261016/ADR](../adr/browserinput-261016-native-input-and-paste.md). This focused delivery implements the approved prototype and repairs, not a broader clipboard bridge.

## Architecture and Lifecycle

The existing Runner → backend socket → web connection remains the sole live Browser transport. Runner pairs each image with at most 16 content-free editable rectangles and document-local IDs (no labels/values). It reads geometry before/after capture and retains their unchanged-region intersection. A replaced child document retires only its own receiver geometry, preserving independently verified main/other-frame receivers and image streaming. Native open Shadow DOM and untransformed frame chains are probed; ambiguous clipping/hits/transforms are omitted. Local receiver keys combine attachment, navigation and editable ID, preserving actual DOM node identity across ordinary frames. Read-only/stale state disables local input.

The web interaction hook binds the selected native receiver to the acknowledged frame scope. Native paste is consumed once and its receiver cleared; Ctrl/Cmd+V is left to the local OS rather than forwarded remotely. The address-bar button invokes a feature-detected clipboard read synchronously in its user gesture without an application confirmation dialog. No clipboard value enters React state. Duplicate reads are excluded; completion is ignored if selection, authority, attachment, navigation, dimensions or receiver changes. A newer acknowledged frame may be used only within the same live scope with the same editable identity. Empty/oversized/denied/unsupported and local delivery failures have fixed localized feedback. The existing remote conflict/unknown-outcome notices remain authoritative; local 'sent' feedback does not claim site success.

A typed paste action carries editable ID and unchanged text within the existing 32,768-character and 64-KiB full-message bounds. Runner verifies acknowledged-region membership, current authority/source, interaction guard, and native active-element/frame-chain identity immediately before insertion. It does not refocus or retry. Native `keyboard.insert_text` retains current native selection semantics; custom remote paste-event behavior is not promised.

Plain user pointer presses retain initiating attachment identity for one popup notification. Modifiers are delivered as real bounded key transitions and background clicks never nominate a foreground owner. Popup state is consumed once and cleared by navigation, new manipulation, Agent actions or attachment cleanup. Only the initiating attachment receives the opened target. The web refreshes projection and selects it only while its origin is still selected; explicit user selection cancels pending preference. Reconnects cannot replay another attachment's notification.

Playwright delivers a popup only after its initial response, which can follow the completed pointer operation. A source-owned private supported-SDK CDP session therefore records content-free native `targetCreated` IDs whose opener is the exact managed native page while the pointer operation is active. Pointer eligibility closes in `finally` at mouseup/cancel. The delayed SDK popup consumes only its exact native target ID in the same context, never a last-click/timer slot. Records are bounded and retire on target destruction, new manipulation, navigation or attachment cleanup; listeners/sessions are detached with the live source. No public CDP endpoint, network listener, clipboard protocol or new authorization mode is introduced. Web pending preference separately requires the same resource, attachment, navigation and current hint after projection refresh.

## Design Authority

Design revision: `1`.

| ID | Mechanism | Authority | Classification |
| --- | --- | --- | --- |
| M1 | Native event and explicit button plaintext on existing stream, with no payload persistence | REQ-1; ADR-D1; current Session Browser Spec | derived |
| M2 | Document-local editable geometry and stable trusted-touch receivers | REQ-2; ADR-D2 | decided |
| M3 | Exact acknowledged source, current native destination and no-replay insertion guard | REQ-1; REQ-2; current Session Browser Spec | derived |
| M4 | Initiator-only ordinary popup preference, preserving background/user choice | REQ-3; current source/attachment authority | required |
| M5 | Native unmasked live and intentional captures | REQ-4 | required |

## Removal and Replacement

| Existing behavior | Authority | Replacement | Boundary | Verification |
| --- | --- | --- | --- | --- |
| Credential field selectors and screenshot masks | REQ-4 | Native website rendering | Runner live/capture calls | Actual image/capture regression; delete obsolete mask test |
| Unconditional mobile blur/refocus | REQ-2 | Direct current native receiver activation | Web touch/input handlers | Stable-node and non-input-touch component tests |
| Synthetic preview-only toolbar injection and confirmation state | REQ-1 | Actual component paste controls, synthetic API adapter only in stories | Story fixtures | Actual interaction plays |

No database migration, new public API, generated client, runtime option or provider change is needed. Ship matching Runner/backend/web builds; old streams are not replayed. Rollback is a code/image rollback with no persisted clipboard data to restore. Existing opt-in and TLS policy are unchanged. Diagnostics carry fixed outcomes, never values.

## Test Strategy

Use the existing representative Session Browser E2E with one plaintext paste through its normal authenticated socket and real Runner. Existing testenv prerequisites/fixture web app are needed for the cross-deployment boundary, not as a replacement for the web journey. Credentials remain in its normal ephemeral prerequisite snapshot; no live-account secrets or real clipboard content enter evidence. Run in normal required CI, fail on boundary/behavior errors; unavailable optional physical-device checks are reported as unverified, not synthetic passes.

Focused strict contract tests cover bounds/unknown fields/geometry. Real-SDK Runner tests cover native inputs/password/textarea/shadow/frame insertion, target changes, read-only/conflict and popup ownership/background behavior. Actual-component stories cover button/native paste, denied/unavailable/oversized/pending/stale destination, duplicate suppression, stable receiver focus and non-input touch. Run formatting, lint, typecheck, representative tests and static builds. Record commands, results and scope of physical-device evidence without input payloads.

## Authority and Feasibility

Every mechanism maps to confirmed Requirements or unchanged Browser authority; no additional product decision or new architecture authority is created. Existing direct text insertion, current-source validation, authenticated stream, native frame/shadow evaluation and the tested iPhone receiver primitive establish feasibility. Dynamic geometry/custom editor and physical-product behavior remain explicit evidence limits.

## Design Approval

- Mode: Collaborative.
- Decision owner: Requester.
- Date: 2026-10-16 KST.
- Scope authorization: The requester reviewed the actual-component prototype, requested no confirmation popup, then explicitly instructed implementation of that flow and the previously confirmed repairs.
- Revision and mechanism set recorded for that bounded implementation: revision `1`, `M1–M5`.
- No separate document-review approval is claimed; the direct implementation instruction authorizes the reviewed behavior and its necessary existing-authority fences. Any broader clipboard or new product behavior requires a new decision.

## Verification Evidence

Source commit `42d5433386ffc5ad0188151c725373f8d7e6dae9` passed [required CI](https://github.com/azents/azents/actions/runs/38777825524): 39 successful checks and one conditional Helm skip. All five E2E lanes passed. The web-lane JUnit artifact records `test_session_browser_engine_native_input_dialog_and_reconnect` passing in 24.934 seconds (including the synthetic authorized local-paste event through the actual Web/backend/Runner password insertion boundary) and `test_session_browser_capture_model_image_and_original_publication` passing in 16.283 seconds, neither skipped.

Local validation passed 63 Runner Browser/popup tests, 39 runtime-control contract tests, 28 backend socket tests, 543 web unit tests, and all 60 actual-component stories with automatic accessibility checks. Ruff/Ty, web formatting/lint/typecheck, Storybook build, E2E-substrate static checks, documentation validation and commit hooks passed. Independent read-only review findings were corrected and targeted re-review found no remaining issue.

Physical iPhone product integration and native OS clipboard-consent/callout UI remain unverified; the earlier physical receiver-primitive experiment and desktop/component automation do not establish those results. No merge, deployment or Runtime restart was performed.
