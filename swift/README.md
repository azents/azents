# Swift / iOS Build Foundation

The native iOS application lives in `swift/apps/azents-ios`, following the
language-first layout used by `python/` and `typescript/`. The application
currently displays **Azents / Hello, world!** and has no Azents server dependency.

## Prerequisites

- macOS with Xcode 26.0.1 at `/Applications/Xcode_26.0.1.app`
- The iOS 26.0.1 simulator runtime and iPhone 17 simulator device type
- Standard macOS tools: Bash, curl, unzip, shasum, ditto, and Python 3.11+

`toolchain.sh` pins the Xcode/runtime selection and XcodeGen/SwiftLint downloads.
The tools are fetched over HTTPS and verified against SHA-256 before use. No
Homebrew, global package installation, Apple developer account, or signing
credentials are required. The bootstrap does not download Xcode or simulator
runtimes; missing prerequisites fail explicitly.

## Local Commands

Run from the repository root:

```console
bash swift/scripts/ios.sh bootstrap
bash swift/scripts/ios.sh generate
bash swift/scripts/ios.sh format
bash swift/scripts/ios.sh format-check
bash swift/scripts/ios.sh lint
bash swift/scripts/ios.sh test
bash swift/scripts/ios.sh build
```

`bash swift/scripts/ios.sh ci` runs the same full sequence used by CI, except
formatting is checked rather than rewritten.

- **Formatting:** toolchain `swift-format`, two-space indentation and
  100-character lines.
- **Lint:** strict SwiftLint checks for unsafe casts/tries/unwraps, naming, and
  unused bindings. Layout is owned by the formatter, not a competing formatter.
- **Compile:** Swift 6 language mode, complete concurrency checking, warnings
  treated as errors.
- **Tests:** XCTest UI launch test asserts the real Hello World screen and keeps
  a screenshot in the result bundle. Only a fresh test-owned simulator is
  created, booted, shut down, and deleted.

There is no separate SPM dependency graph yet. XcodeGen's `project.yml` describes
application/test targets and schemes; generated project files are not committed.
The bootstrap bundle identifier is not an App Store registration or a promise
about the identity of a future signed app.

## CI and Downloading Artifacts

The **iOS** workflow runs on standard GitHub-hosted `macos-15` for relevant pull
requests, relevant pushes to `main`, and manual dispatch. It uses the selected
Xcode, checks quality, executes simulator tests, and builds Release products.
Its `ios-quality-build` job fails when any required operation fails.

Open a completed workflow run's **Artifacts** section:

- `ios-app-builds-<commit>` (14 days):
  - `Azents-iOS-Simulator.app.zip`: simulator application bundle.
  - `Azents-iOS-Unsigned.xcarchive.zip`: device archive without code signing.
  - `manifest.json`: actual checked-out source commit, selected Xcode, ZIP hashes,
    and an explicit non-installable marker.
- `ios-diagnostics-<commit>` (7 days): build/test logs and `.xcresult`, including
  the Hello World test screenshot. Diagnostics are attempted even after failure.

Pull-request runs build the checked-out merge commit, not necessarily the branch
head; the manifest records that exact source. GitHub artifact downloads require
appropriate repository access. They expire according to the retention above;
these are not permanent releases or packages.

Neither app artifact is an iPhone-installable IPA. Personal-device installation,
signing/provisioning, TestFlight, and App Store publication are the next delivery
stage and are deliberately not configured here. Unzip a simulator artifact and
install it only on a compatible Mac simulator when needed:

```console
xcrun simctl install booted Azents.app
```

CI has read-only repository permission, uses commit-pinned Actions, and requests
no signing or store secrets. The existing server/web release workflow is
unchanged. Linux hosts can inspect source/configuration and run shell syntax
checks, but real iOS compilation and UI validation happen on macOS.
