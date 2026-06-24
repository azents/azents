"use client";

/**
 * Subagent execution block.
 *
 * message flow to display clickable subagent card.
 * when running Loader + name + elapsed time, completewhen name + result summary display.
 * when clicked SubagentDetailModal opens..
 *
 * Background subagent parent run even after end run continues, so,
 * elapsed time periodically update in progress display.
 */

import {
  Badge,
  Group,
  Loader,
  Paper,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { IconRobot } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { ChatMessage } from "../types";

interface SubagentBlockProps {
  message: ChatMessage;
  /** subagent current run duringwhether whether */
  isRunning: boolean;
  /** complete result text (subagent_end of content) */
  resultText?: string | null;
  /** click when detail modal open */
  onClick: () => void;
}

/**
 * seconds elapsed time "M:SS" format with convert..
 * 1whenduration exceeds "H:MM:SS" returns..
 */
function formatElapsed(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  const pad = (n: number): string => n.toString().padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(secs)}`;
  }
  return `${minutes}:${pad(secs)}`;
}

/**
 * run during status in 1updated every second elapsed time(sec) text hook.
 * run itext status in 0 text tick stops..
 */
function useElapsedSeconds(
  startedAt: string | null,
  isRunning: boolean,
): number {
  const [elapsed, setElapsed] = useState<number>(() => {
    if (!startedAt) {
      return 0;
    }
    const start = new Date(startedAt).getTime();
    return Number.isFinite(start)
      ? Math.max(0, (Date.now() - start) / 1000)
      : 0;
  });

  useEffect(() => {
    if (!isRunning || !startedAt) {
      return;
    }
    const start = new Date(startedAt).getTime();
    if (!Number.isFinite(start)) {
      return;
    }
    const tick = (): void => {
      setElapsed((Date.now() - start) / 1000);
    };
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [isRunning, startedAt]);

  return elapsed;
}

export function SubagentBlock({
  message,
  isRunning,
  resultText,
  onClick,
}: SubagentBlockProps): React.ReactElement {
  const t = useTranslations("chat.subagent");
  const name = message.metadata?.subagent_name ?? "Subagent";
  const elapsedSeconds = useElapsedSeconds(message.createdAt, isRunning);

  return (
    <UnstyledButton onClick={onClick} mb="md">
      <Paper
        px="sm"
        py="xs"
        radius="md"
        shadow="xs"
        style={{
          cursor: "pointer",
          border: "1px solid var(--mantine-color-default-border)",
          transition: "background 150ms",
        }}
      >
        <Group gap="xs" wrap="nowrap">
          {isRunning ? (
            <Loader size={16} />
          ) : (
            <IconRobot size={16} color="var(--mantine-color-blue-6)" />
          )}
          <Text size="sm" fw={500} truncate>
            {name}
          </Text>
          {isRunning && elapsedSeconds > 0 && (
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              {formatElapsed(elapsedSeconds)}
            </Text>
          )}
          <Badge
            size="xs"
            variant="light"
            color={isRunning ? "blue" : "green"}
            ml="auto"
            style={{ flexShrink: 0 }}
          >
            {isRunning ? t("running") : t("completed")}
          </Badge>
        </Group>
        {!isRunning && resultText && (
          <Text size="xs" c="dimmed" lineClamp={2} mt={4}>
            {resultText}
          </Text>
        )}
      </Paper>
    </UnstyledButton>
  );
}
