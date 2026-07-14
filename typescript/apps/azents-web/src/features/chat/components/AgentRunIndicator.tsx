"use client";

/**
 * Agent model call progress indicator rendered inline in the chat timeline.
 */

import { Box, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import styles from "./AgentRunIndicator.module.css";
import {
  startModelCallDurationTimer,
  visibleModelCallDurationSeconds,
} from "./modelCallDuration";

interface AgentRunIndicatorProps {
  modelCallStartedAt: string | null;
}

function useVisibleModelCallDurationSeconds(
  startedAt: string | null,
): number | null {
  const [, setTick] = useState(0);

  useEffect(
    () =>
      startModelCallDurationTimer(
        startedAt,
        () => setTick((tick) => tick + 1),
        (callback, delay) => window.setInterval(callback, delay),
        (timerId) => window.clearInterval(timerId),
      ),
    [startedAt],
  );

  return visibleModelCallDurationSeconds(startedAt, Date.now());
}

export function AgentRunIndicator({
  modelCallStartedAt,
}: AgentRunIndicatorProps): React.ReactElement {
  const durationSeconds =
    useVisibleModelCallDurationSeconds(modelCallStartedAt);

  return (
    <Box className={styles.root}>
      <Box className={styles.dots} role="status" aria-label="Agent is working">
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
      </Box>
      {durationSeconds !== null && (
        <Text className={styles.duration} c="dimmed" size="xs">
          {durationSeconds}s
        </Text>
      )}
    </Box>
  );
}
