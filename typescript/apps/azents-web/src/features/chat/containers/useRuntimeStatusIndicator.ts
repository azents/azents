"use client";

import { useEffect, useState } from "react";
import type { RuntimeStatus } from "@azents/session-core/types";

export interface RuntimeStatusIndicatorProps {
  status: RuntimeStatus;
}

export function useRuntimeStatusIndicator({
  status,
}: RuntimeStatusIndicatorProps): RuntimeStatusIndicatorProps & {
  visible: boolean;
} {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (status === "ready") {
      setVisible(true);
      const timer = window.setTimeout(() => setVisible(false), 3000);
      return () => window.clearTimeout(timer);
    }
    setVisible(status === "initializing" || status === "error");
  }, [status]);
  return { status, visible };
}
