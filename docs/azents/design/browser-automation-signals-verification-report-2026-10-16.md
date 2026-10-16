---
title: "Browser Automation Signal Reduction Verification"
created: 2026-10-16
tags: [browser, runtime, testing]
document_role: supporting
document_type: supporting-verification-report
---

# Browser Automation Signal Reduction Verification

## Requested scope

Keep standard Playwright, suppress avoidable explicit automation markers, and apply stealth to managed Session browser contexts. Preserve authority, per-Session persistent profiles, native input, live attachment, sandbox/proxy policy and Runtime lifecycle. Do not replace the driver with Patchright, add proxy rotation or CAPTCHA solving, or claim undetectability.

## Implementation boundary

The Runner selects the installed full Chromium with `channel="chromium"` in new headless mode for both its existing readiness probe and its persistent contexts. It disables Blink AutomationControlled and removes the enable-automation default when present. The existing probe derives the native OS/browser User-Agent; a native context override removes only its HeadlessChrome token. This also normalizes appVersion and request User-Agent without inventing an OS or browser version. Native full-Chromium client-hint brands, including GREASE, are retained.

The pinned playwright-stealth package is explicitly applied to each persistent context before site navigation. Its convenience wrapper does not wrap persistent-context creation. Platform, language and GPU spoofing are disabled to preserve native identity. Two inline type-checker suppressions document upstream constructor annotations that do not describe the supported None values for disabled overrides.

No new public endpoint, UI control, browser port, persistent version, authorization capability or proxy is introduced. Existing Session contexts are not replaced. Activation requires a new context under the updated Runner; this work does not restart any current Runtime.

## Independent review and regression boundary

Independent review found two issues in an initial implementation: a synthesized client-hint header dropped the native GREASE brand, and appVersion retained HeadlessChrome. Both were corrected using native context identity rather than more page shims. Targeted re-review reported no remaining blockers and independently passed 29 browser tests, including initial-page scripts, iframes, popup identity, parsed HTTP/page brand equality, Session cookie isolation, native browser flows and failed setup cleanup. Readiness-probe new-page/evaluation failure cleanup was independently checked.

The complete Runner suite passed: 571 tests in 100.68 seconds. Ruff, formatting, the configured type checker, E2E fixture static checks, documentation catalog and whitespace validation also passed. Runner regression includes existing dialogs, popup/download/upload handling, native input, stale targets, Session persistence/isolation, live viewing, field editing and shutdown cleanup. The assembled-product authenticated Browser E2E fixture also rejects exposed webdriver, User-Agent, appVersion and low-entropy HTTP/page client-hint HeadlessChrome markers before its existing handoff/input/reconnect flow can pass.

Submitted-SHA CI evidence is recorded in the PR; local synthetic checks are not represented as assembled-product E2E. The initial CI attempt passed Runner and all four required E2E lanes but failed the Browser Web flow at address navigation. A same-SHA retry instead failed at first WebDriver use: Selenium explicitly reported its 120-second unused-session expiration during prior native Runtime preparation. The fixture now creates its function-owned WebDriver immediately before first Web interaction, preserving cleanup/artifact ownership. Address input also explicitly releases Control and confirms the complete controlled URL value before Enter; no retries, sleeps, timeout increases or assertion removal were added. The initial navigation failure remains distinct until the updated flow is measured in CI.

## Live site diagnostic

A separate isolated local workspace used the actual modified RunnerBrowserManager to visit Naver Shopping home and a public keyboard search. webdriver was false; User-Agent and appVersion had no HeadlessChrome token; platform remained Linux and brands retained Chromium plus native GREASE. Home still returned HTTP 405 and search HTTP 418. This did not establish successful Naver access or its blocking cause. No login, CAPTCHA response, purchase, user profile access or IP change occurred.

## Limits

Standard Playwright CDP transport and internal domain calls remain. This change does not promise removal of every fingerprint, worker/high-entropy signal, behavioral detector or network reputation factor. Full Chromium can have a different resource footprint from headless shell; CI and product E2E are required to establish compatibility. No merge, deployment, live profile migration, native user tab closure or Runtime restart was performed.
