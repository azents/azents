#!/usr/bin/env bash
set -euo pipefail

SWIFT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$SWIFT_ROOT/.." && pwd)"
APP_ROOT="$SWIFT_ROOT/apps/azents-ios"
BUILD_ROOT="$SWIFT_ROOT/.build"
TOOLS_ROOT="$SWIFT_ROOT/.tools"
source "$SWIFT_ROOT/toolchain.sh"
source "$SWIFT_ROOT/scripts/simulator-diagnostics.sh"

require_macos() {
  if [ "$(uname -s)" != Darwin ]; then
    printf 'iOS commands require macOS and Xcode %s; use the iOS CI workflow from Linux.\n' \
      "$XCODE_VERSION" >&2
    exit 1
  fi
  export DEVELOPER_DIR="/Applications/Xcode_${XCODE_VERSION}.app/Contents/Developer"
  if [ ! -d "$DEVELOPER_DIR" ]; then
    printf 'Required Xcode is missing: %s\n' "$DEVELOPER_DIR" >&2
    exit 1
  fi
}

install_tool() (
  name="$1"
  url="$2"
  checksum="$3"
  binary_path="$4"
  destination="$TOOLS_ROOT/$name"
  if [ -f "$destination/.archive-sha256" ] \
    && [ "$(cat "$destination/.archive-sha256")" = "$checksum" ] \
    && [ -x "$destination/$binary_path" ]; then
    exit 0
  fi
  temporary="$(mktemp -d)"
  trap 'rm -rf "$temporary"' EXIT
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    "$url" -o "$temporary/tool.zip"
  printf '%s  %s\n' "$checksum" "$temporary/tool.zip" | shasum -a 256 --check
  mkdir "$temporary/extracted"
  unzip -q "$temporary/tool.zip" -d "$temporary/extracted"
  test -x "$temporary/extracted/$binary_path"
  printf '%s\n' "$checksum" > "$temporary/extracted/.archive-sha256"
  mkdir -p "$TOOLS_ROOT"
  rm -rf "$destination"
  mv "$temporary/extracted" "$destination"
)

bootstrap() {
  install_tool xcodegen \
    "https://github.com/yonaskolb/XcodeGen/releases/download/$XCODEGEN_VERSION/xcodegen.zip" \
    "$XCODEGEN_SHA256" xcodegen/bin/xcodegen
  install_tool swiftlint \
    "https://github.com/realm/SwiftLint/releases/download/$SWIFTLINT_VERSION/portable_swiftlint.zip" \
    "$SWIFTLINT_SHA256" swiftlint
  "$TOOLS_ROOT/xcodegen/xcodegen/bin/xcodegen" --version
  "$TOOLS_ROOT/swiftlint/swiftlint" version
  xcodebuild -version
  xcrun swift --version
}

generate() {
  "$TOOLS_ROOT/xcodegen/xcodegen/bin/xcodegen" generate \
    --spec "$APP_ROOT/project.yml" --project "$APP_ROOT"
}

format_sources() {
  xcrun swift-format format --in-place --recursive \
    --configuration "$SWIFT_ROOT/.swift-format" "$APP_ROOT/Sources" "$APP_ROOT/UITests"
}

check_format() {
  xcrun swift-format lint --strict --recursive \
    --configuration "$SWIFT_ROOT/.swift-format" "$APP_ROOT/Sources" "$APP_ROOT/UITests"
}

lint_sources() {
  (cd "$SWIFT_ROOT" && "$TOOLS_ROOT/swiftlint/swiftlint" lint \
    --strict --config "$SWIFT_ROOT/.swiftlint.yml")
}

test_app() (
  mkdir -p "$BUILD_ROOT"
  runtime_id="$(simulator_stage list-runtimes xcrun simctl list runtimes --json | python3 -c '
import json, sys
version = sys.argv[1]
matches = [r["identifier"] for r in json.load(sys.stdin)["runtimes"]
           if r.get("isAvailable") and r.get("version") == version
           and r["identifier"].startswith("com.apple.CoreSimulator.SimRuntime.iOS-")]
if len(matches) != 1:
    sys.exit(f"Expected one available iOS runtime {version}; found {matches}")
print(matches[0])
' "$SIMULATOR_RUNTIME_VERSION")"
  simulator_id="$(simulator_stage create xcrun simctl create Azents-CI "$SIMULATOR_DEVICE_TYPE" "$runtime_id")"
  trap 'xcrun simctl shutdown "$simulator_id" >/dev/null 2>&1 || true
        xcrun simctl delete "$simulator_id" >/dev/null 2>&1 || true' EXIT
  rm -rf "$BUILD_ROOT/UITests.xcresult"
  # XCTest owns simulator startup and proves readiness by launching the real app.
  simulator_stage test xcodebuild test \
    -project "$APP_ROOT/Azents.xcodeproj" -scheme Azents -configuration Debug \
    -destination "platform=iOS Simulator,id=$simulator_id" \
    -derivedDataPath "$BUILD_ROOT/DerivedData" \
    -resultBundlePath "$BUILD_ROOT/UITests.xcresult" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
    2>&1 | tee "$BUILD_ROOT/test.log"
  rm -rf "$BUILD_ROOT/screenshots"
  xcrun xcresulttool export attachments --path "$BUILD_ROOT/UITests.xcresult" \
    --output-path "$BUILD_ROOT/screenshots"
)

build_app() {
  mkdir -p "$BUILD_ROOT/artifacts"
  xcodebuild build \
    -project "$APP_ROOT/Azents.xcodeproj" -scheme Azents -configuration Release \
    -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
    -derivedDataPath "$BUILD_ROOT/DerivedData" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
    2>&1 | tee "$BUILD_ROOT/simulator-build.log"
  test -d "$BUILD_ROOT/DerivedData/Build/Products/Release-iphonesimulator/Azents.app"
  ditto -c -k --keepParent \
    "$BUILD_ROOT/DerivedData/Build/Products/Release-iphonesimulator/Azents.app" \
    "$BUILD_ROOT/artifacts/Azents-iOS-Simulator.app.zip"
  rm -rf "$BUILD_ROOT/Azents-Unsigned.xcarchive"
  xcodebuild archive \
    -project "$APP_ROOT/Azents.xcodeproj" -scheme Azents -configuration Release \
    -sdk iphoneos -destination 'generic/platform=iOS' \
    -archivePath "$BUILD_ROOT/Azents-Unsigned.xcarchive" \
    -derivedDataPath "$BUILD_ROOT/DerivedData" \
    CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
    2>&1 | tee "$BUILD_ROOT/archive.log"
  test -d "$BUILD_ROOT/Azents-Unsigned.xcarchive/Products/Applications/Azents.app"
  ditto -c -k --keepParent "$BUILD_ROOT/Azents-Unsigned.xcarchive" \
    "$BUILD_ROOT/artifacts/Azents-iOS-Unsigned.xcarchive.zip"
  python3 - "$REPO_ROOT" "$BUILD_ROOT/artifacts" "$XCODE_VERSION" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

repository, output, xcode = sys.argv[1:]
output = Path(output)


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


manifest = {
    "source_commit": subprocess.check_output(
        ["git", "-C", repository, "rev-parse", "HEAD"], text=True
    ).strip(),
    "xcode": xcode,
    "personal_device_installable": False,
    "artifacts": [
        {"name": p.name, "sha256": checksum(p)}
        for p in sorted(output.glob("*.zip"))
    ],
}
(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
}

command="${1:-help}"
if [ "$command" = help ]; then
  printf 'Usage: bash swift/scripts/ios.sh {bootstrap|format|format-check|lint|generate|test|build|ci}\n'
  exit 0
fi
require_macos
case "$command" in
  bootstrap) bootstrap ;;
  format) format_sources ;;
  format-check) check_format ;;
  lint) lint_sources ;;
  generate) generate ;;
  test) generate; test_app ;;
  build) generate; build_app ;;
  ci)
    bootstrap
    check_format
    lint_sources
    generate
    test_app
    build_app
    ;;
  *) printf 'Unknown command: %s\n' "$command" >&2; exit 2 ;;
esac
