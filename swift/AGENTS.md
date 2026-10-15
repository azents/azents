# Swift Workspace

Swift code follows the repository's language-first layout:

- `apps/azents-ios/`: native iOS application and its UI tests.
- Future reusable Swift libraries belong under `libs/` when actually needed.

Read `.claude/rules/conventions.md` and
`.claude/rules/swift-conventions.md` before editing Swift sources. Read applicable
convention bodies; do not copy these rules into individual app instructions.
Git-tracked text and comments follow the repository's English language rule.

## Quality and Build

All application commands run from the repository root:

```console
bash swift/scripts/ios.sh bootstrap
bash swift/scripts/ios.sh format
bash swift/scripts/ios.sh format-check
bash swift/scripts/ios.sh lint
bash swift/scripts/ios.sh test
bash swift/scripts/ios.sh build
```

`ci` runs bootstrap, format check, lint, generated project, simulator tests, and
unsigned builds in that order. The same entry point is used in GitHub Actions.
Formatting uses the selected Xcode's `swift-format`; lint uses checksummed
SwiftLint. The compiler uses Swift 6 isolation checks and treats warnings as
errors. Do not weaken these checks to make a build pass.

These commands require macOS and the exact Xcode in `toolchain.sh`. A Linux Agent
must use the GitHub macOS CI job for real SwiftUI compilation and simulator
tests; do not report Linux structural checks as an iOS build.

## Project and Tests

`project.yml` is the Xcode project input. XcodeGen is bootstrapped at a fixed
version and checksum; generated `.xcodeproj` directories are ignored. Do not add
a parallel hand-maintained project. The application currently has no Swift
package dependencies or server connection.

UI tests launch the real app and wait for observable UI state. Use XCTest
expectations/element waits, not fixed sleeps. Deterministic unit tests should be
added when domain logic exists; do not manufacture a domain layer for static
Hello World text.

## Artifacts and Security

CI publishes simulator `.app` and unsigned device `.xcarchive` ZIPs, a source
manifest, logs, and test results. These are build evidence, not iPhone-installable
IPAs. This stage has no Apple account, signing key, provisioning profile,
TestFlight, or store submission. Do not add those to solve an unsigned-build
failure. Never give fork PR jobs signing/upload secrets.
