#!/usr/bin/env bash

# Keep command stdout unchanged for JSON and simulator identifier consumers.
simulator_stage() {
  local stage="$1" status=0
  shift
  printf '%s stage=%s event=start\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$stage" \
    | tee -a "$BUILD_ROOT/simulator-setup.log" >&2
  "$@" || status=$?
  printf '%s stage=%s event=end exit_code=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$stage" "$status" \
    | tee -a "$BUILD_ROOT/simulator-setup.log" >&2
  return "$status"
}
