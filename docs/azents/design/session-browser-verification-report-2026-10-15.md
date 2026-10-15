---
title: "Session Browser Delivery Verification Report"
created: 2026-10-15
tags: [browser, runtime, session, verification]
document_role: supporting
document_type: supporting-verification-report
---

# Session Browser Delivery Verification

Authority: [Requirements](../requirements/browsercmd-261014-session-browser.md)
REQ-1–15, accepted [ADR](../adr/browsercmd-261014-session-browser.md) D1–D5,
approved [Design](browsercmd-261014-session-browser.md) revision 3 M1–M18.
Current behavior belongs in the [Session Browser flow](../spec/flow/session-browser.md).

## Delivery and acceptance

- Phase 1: [shared transport PR #2262](https://github.com/azents/azents/pull/2262).
- Phase 2: [Runner/tools PR #2263](https://github.com/azents/azents/pull/2263).
- Phase 3: [authenticated viewer PR #2268](https://github.com/azents/azents/pull/2268)
  at `15ae00a18f18d32ef2a4d885db0a09bb1c4c9c10` after the reviewed CI corrections.
- Phase 4: [managed guidance and file/model/publication PR #2272](https://github.com/azents/azents/pull/2272)
  at `6f7cba00c24df0f1f60ee0ed259cb776f690e455` passed functional CI before
  this final documentation-only completion and plan cleanup.
- Scoped implementation and delivery validation completed on 2026-10-15.
  Requirements and Design carry the same implementation date; current behavior
  is promoted to Living Specs and temporary execution plans are removed.
- Design delta: None. Merge, deployment and infrastructure mutations are not
  part of this verification authorization.

## Completed root evidence

| Boundary | Result and interpretation |
| --- | --- |
| Shared control | 450 tests passed, including propagating child cancellation followed by new work on the same Runner. Parent cancellation and unexpected task failures still propagate. |
| Runner resources/viewer | 479 tests passed, including actual SDK navigation/resize before old-image display, stale source denial, dialogs/composition, cleanup and fixed-category capture diagnostics. |
| API/Control authority | 469 integrated tests passed, including 63 focused source/Owner checks. Validation stalls remain attachment-local, source setup expires as a whole, and held-input cleanup cannot cross scope. |
| Web | 522 tests passed after adding a same-scope render-to-ACK keyboard/composition regression. Spatial input retains exact-frame fencing. |
| Real components | 40 story plays passed at DPR 1 and scale 1 with loaded product fonts, zero axe violations and horizontal overflow. This is component evidence, not OS-mobile acceptance. |
| Managed Skill and file services | 136 tests passed across real release packaging, projection/load, schema examples/provider lowerers, existing immutable Skill projection semantics and image/publication/transfer services. |
| E2E fixture support | 1,279 Docker-free support tests passed, including the journal-isolation regression and both native text and multimodal Browser result parsing. |
| Original-file journey | Run-isolated normal-authentication Engine E2E passed in 51.58 seconds: actual `load_skill` → `browser_open` → `browser_observe(image)` → model image → Runtime original inspection → `present_file` → authorized Exchange download. Download SHA-256, size, PNG header and dimensions equal the saved original. |
| Authenticated live viewer | Two same-build prepared-image E2Es passed in 75.48 and 75.46 seconds, including complete mixed-case text, address/history/reload, reconnect, final authentication revocation and stale target denial. They do not prove a previous intermittent SDK capture failure's cause was fixed. |

The file journey uses normal account/Agent/Session setup, current public
session-folder preparation and the managed Docker Runner. Its model fixture
chooses calls deterministically but never substitutes product browser commands,
file materialization, transfer or publication. It records only model identity,
completed fixture call IDs and image-presence metadata, not page bodies, image
data, credentials or full tool outputs.

The Browser-specific journal is cleared immediately before each handoff.
Independent review identified that an older positive entry could otherwise
satisfy the provider-image assertion when a proxy process was reused. The
regression seeds an older positive witness, exercises the actual DELETE handler,
and verifies a new zero-image entry cannot inherit that witness. Original
Runtime/Exchange identity and hash checks remain separate from model evidence.

The passing original-file journey used backend image
`sha256:da239379d4bd1530831812188bcf12ad2c9b7d410350a001c38bcc4f2d5d75e1`
with 2,468 verified backend/shared Python sources and Runner image
`sha256:9548028912299c4a8c2c78e35857d6419b900862f27667d22c021ce08925e42d`
with 63 verified Runner/shared Python sources. A subsequent Runner image
`sha256:9361e44ba27d51db0533925935e287f7da0f8ae004ee26a7e07a8e835d34c0c1`
adds content-free capture failure diagnostics; its 63 sources also match.

## Independent review

The single reviewer `/root/browser-feature-reviewer` reviewed the complete
Phase 3 diff and the corrections, including two additional shared cancellation
paths. Initial review independently ran 324 checks; targeted re-review ran 91.
Code review passed after resolving:

- held pointer/composition cleanup discarded after a new displayed ACK;
- unbounded authority I/O blocking the shared Runner response reader;
- an obsolete undisplayed image blocking new-navigation/viewport delivery;
- total setup deadline and unexpected cleanup exception visibility; and
- canceled child operation reaping terminating the Runner.

Phase 4's complete-diff review covered the Skill, fixtures, non-spatial ACK
correction and adjacent Specs. Independent checks passed 85 cases. The reviewer
identified the journal-isolation evidence defect; its correction was confirmed
with four independent proxy checks and the isolated 51.58-second actual E2E.
The same reviewer completed targeted security re-review of the subsequent
transport-composition correction with 42 passing checks. Root's focused
trust/source validation passed 138 checks. The complete updated phase review
includes REQ-15 and navigation; final authenticated viewer and CI evidence
is recorded below.

## Final CI and Resolved Regressions

All four PRs remain open and unmerged. At the completion checkpoint:

- PR #2262: 38 successful checks, two conditionally skipped.
- PR #2263: 36 successful checks, none unfinished.
- PR #2268 at `15ae00a18f18d32ef2a4d885db0a09bb1c4c9c10`:
  35 successful checks, two conditionally skipped.
- PR #2272 at `6f7cba00c24df0f1f60ee0ed259cb776f690e455`:
  34 successful checks, two conditionally skipped.

These results include all required E2E shards and Web E2E. Final documentation
cleanup triggers its own CI; the checkpoint above identifies the tested functional
head rather than claiming a result for an as-yet-uncreated documentation commit.

Earlier Phase 3 CI exposed two underlying regressions, now corrected:

1. Browser Web E2E did not observe the full keyboard text. A same-scope
   render-to-ACK race was identified and corrected in Phase 4. A subsequent
   prepared-image E2E passed the complete text and native navigation/reload
   assertions but initially still failed the final revocation assertion. Two
   subsequent same-build complete viewer runs passed; the earlier SDK capture
   failure remains explicitly recorded below rather than discarded.
2. A subscription-usage isolation E2E asserted that its selected diagnostic
   records were nonempty. Its cause was Phase 3 changing the shared Public API
   fixture from deployed to local environment, which changed logging format.
   Root restored the fixture environment and removed the unintended Browser-only
   environment gate in client composition. Browser now honors the same existing
   ordinary Control endpoint/CA/explicit insecure opt-in as other API clients.
   Missing trust still fails without opt-in, a configured CA always selects TLS,
   and Browser-only proof/source admission remains mandatory. No new transport
   setting, default plaintext, credential reuse or automatic downgrade is added.
   The corrected deployed-API integrated run reported passing subscription,
   viewer and file-publication assertions. Its process/teardown summary was not
   returned, so only those individual assertions are evidence. Subsequent
   complete CI passed the corrected subscription and Browser journeys together.

## Historical Failures and Remaining Diagnostic Limits

A prior completed local viewer E2E reached final revocation but closed with
`4500 Browser is unavailable` instead of the expected authentication/access
close code. This is not passing revocation evidence. Current bounded,
content-free capture diagnostics support the next investigation without
logging the underlying page or typed content.
Later successful same-build viewer runs and CI satisfy scoped delivery acceptance,
but do not establish the root cause or definitive correction of that earlier
intermittent SDK capture failure.

Other final E2E attempts were interrupted by Runtime replacement/process loss
and have no result. Kubernetes events established one host replacement as
eviction after the container-engine EmptyDir exceeded 40 GiB. The requester
authorized one unused Docker build-cache cleanup, which reclaimed 4.59 GB;
images, containers, volumes and profiles were preserved. No storage-limit
change, deployment or production restart was performed. Prepared, source-matched
images are reused through existing fixture options.

## Scope and limitations

- No production deployment, real account/site acceptance, real iPhone Safari or
  OS-mobile IME acceptance is claimed.
- Product-image probes are synthetic pre-admitted SDK checks, separate from the
  normal authenticated Engine/API/Control journey.
- Native sandbox checks distinguish supported behavior from specifically
  established incompatibility and generic errors. Sandbox-disabled nested
  Runtime evidence does not establish a supported native-sandbox deployment.
- Original capture, actual model imagery and verified file publication are
  separate outcomes. Live frames are volatile, not a new recording store.
- The unagreed known-input collection and page-wide replacement were removed.
  Structural DOM input/credential-attribute omission and generic log privacy
  remain; ordinary visible text, labels, titles and dialog responses are retained.
