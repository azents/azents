"use client";

/**
 * Agent model call progress indicator rendered inline in the chat timeline.
 */

import { Box } from "@mantine/core";
import styles from "./AgentRunIndicator.module.css";

export function AgentRunIndicator(): React.ReactElement {
  return (
    <Box className={styles.root}>
      <Box className={styles.dots} role="status" aria-label="Agent is working">
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
        <span className={styles.dot} aria-hidden="true" />
      </Box>
    </Box>
  );
}
