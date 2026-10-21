"use client";
import { useEffect, useState } from "react";
import {
  startElapsedDurationTimer,
  visibleElapsedDurationSeconds,
} from "../components/elapsedDuration";
interface AgentRunIndicatorProps {
  lastEventReceivedAt: string | null;
}
function useVisibleEventSilenceDuration(
  lastEventReceivedAt: string | null,
): number | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    return startElapsedDurationTimer(
      lastEventReceivedAt,
      () => setTick((tick) => tick + 1),
      (callback, delay) => window.setInterval(callback, delay),
      (timerId) => window.clearInterval(timerId),
    );
  }, [lastEventReceivedAt]);

  return visibleElapsedDurationSeconds(lastEventReceivedAt, Date.now(), 10);
}
export interface AgentRunIndicatorViewProps {
  durationSeconds: number | null;
}
export function useAgentRunIndicatorController({
  lastEventReceivedAt,
}: AgentRunIndicatorProps): AgentRunIndicatorViewProps {
  const durationSeconds = useVisibleEventSilenceDuration(lastEventReceivedAt);
  return { durationSeconds };
}
