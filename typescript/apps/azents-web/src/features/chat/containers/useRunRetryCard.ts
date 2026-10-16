"use client";

import { useDisclosure } from "@mantine/hooks";
import { useEffect, useState } from "react";
import type {
  AgentRunPhase,
  ChatLiveRunRetryState,
  FailedRunAttemptSummary,
  FailedRunFailureMetadata,
} from "@azents/session-core/types";

export type RunRetryCardProps =
  | { variant: "live"; retry: ChatLiveRunRetryState; phase: AgentRunPhase }
  | {
      variant: "terminal";
      message: string;
      failure: FailedRunFailureMetadata;
      canRetry: boolean;
      isRetryPending: boolean;
      onRetry: () => void;
    };

function timestampMs(iso: string): number | null {
  const value = new Date(iso).getTime();
  return Number.isFinite(value) ? value : null;
}

export function useRunRetryCard(props: RunRetryCardProps): {
  props: RunRetryCardProps;
  countdown: number | null;
} {
  const nextRetryAt = props.variant === "live" ? props.retry.nextRetryAt : null;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (nextRetryAt === null) {
      return;
    }
    const target = timestampMs(nextRetryAt);
    if (target === null || target <= Date.now()) {
      setNow(Date.now());
      return;
    }
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [nextRetryAt]);
  const target = nextRetryAt === null ? null : timestampMs(nextRetryAt);
  return {
    props,
    countdown:
      target === null ? null : Math.max(0, Math.ceil((target - now) / 1000)),
  };
}

export function useAttemptHistory({
  attempts,
}: {
  attempts: FailedRunAttemptSummary[];
}): {
  attempts: FailedRunAttemptSummary[];
  opened: boolean;
  toggle: () => void;
} {
  const [opened, { toggle }] = useDisclosure(false);
  return { attempts, opened, toggle };
}
