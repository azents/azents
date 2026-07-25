"use client";

/**
 * Agent model call progress indicator rendered inline in the chat timeline.
 */

import { Box, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import styles from "./AgentRunIndicator.module.css";
import {
  formatElapsedDuration,
  startElapsedDurationTimer,
  visibleElapsedDurationSeconds,
} from "./elapsedDuration";

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

export function AgentRunIndicator({
  lastEventReceivedAt,
}: AgentRunIndicatorProps): React.ReactElement {
  const durationSeconds = useVisibleEventSilenceDuration(lastEventReceivedAt);

  return (
    <Box className={styles.root}>
      <Box className={styles.dots} role="status" aria-label="Agent is working">
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
      </Box>
      {durationSeconds !== null ? (
        <Text className={styles.duration} c="dimmed" size="xs">
          {formatElapsedDuration(durationSeconds)}
        </Text>
      ) : null}
    </Box>
  );
}
