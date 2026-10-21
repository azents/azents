"use client";
import { Box, Text } from "@mantine/core";
import { useAgentRunIndicatorController } from "../containers/useAgentRunIndicatorController";
/**
 * Agent model call progress indicator rendered inline in the chat timeline.
 */
import styles from "./AgentRunIndicator.module.css";
import { ChatTimelineItem } from "./ChatTimelineItem";
import { formatElapsedDuration } from "./elapsedDuration";
import type { AgentRunIndicatorViewProps } from "../containers/useAgentRunIndicatorController";

interface AgentRunIndicatorProps {
  lastEventReceivedAt: string | null;
}

export function AgentRunIndicator(
  props: AgentRunIndicatorProps,
): React.ReactElement {
  return <AgentRunIndicatorView {...useAgentRunIndicatorController(props)} />;
}

export function AgentRunIndicatorView({
  durationSeconds,
}: AgentRunIndicatorViewProps): React.ReactElement {
  return (
    <ChatTimelineItem kind="activity">
      <Box className={styles.root}>
        <Box
          className={styles.dots}
          role="status"
          aria-label="Agent is working"
        >
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
    </ChatTimelineItem>
  );
}
