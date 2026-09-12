import type { ElevationState } from "./types";
import type { AuthMethod } from "@azents/public-client";

export function synchronizeElevationState({
  state,
  methods,
  reset,
}: {
  state: ElevationState;
  methods: AuthMethod[];
  reset: boolean;
}): ElevationState {
  if (reset || state.type === "CHOOSE_METHOD") {
    return { type: "CHOOSE_METHOD", methods };
  }
  return state;
}
