"use client";

import { useEffect, useState } from "react";
import type {
  RuntimeWebActivationDurationProps,
  RuntimeWebActivationState,
  RuntimeWebDurationSeconds,
} from "../types";

/** Transient duration selection stays synchronized with current service observations. */
export function useRuntimeWebActivationDuration(
  state: RuntimeWebActivationState,
): RuntimeWebActivationDurationProps {
  const [duration, setDuration] = useState<RuntimeWebDurationSeconds>(3600);
  useEffect(() => {
    if (state.type === "READY") {
      setDuration(state.service.selected_duration_seconds);
    }
  }, [state]);
  return { duration, onDurationChange: setDuration };
}
