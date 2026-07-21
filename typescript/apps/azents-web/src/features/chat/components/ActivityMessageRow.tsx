"use client";

import { Box, Group, Text } from "@mantine/core";
import { IconBubble, IconTargetArrow } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import {
  activityRowChevronSize,
  activityRowIconSize,
  activityRowSummarySize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import type { ActivityEvent } from "../toolActivityPresentation";
import type { ReactElement } from "react";

interface ActivityMessageRowProps {
  event: ActivityEvent;
}

function activityPreview(content: string): string | null {
  const preview = content
    .replace(/<!--[\s\S]*?-->/gu, "")
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return preview && preview.length > 0 ? preview : null;
}

export function ActivityMessageRow({
  event,
}: ActivityMessageRowProps): ReactElement | null {
  const t = useTranslations("chat");
  if (event.kind !== "goal-control" && event.kind !== "other") {
    return null;
  }

  const label =
    event.kind === "goal-control"
      ? event.message?.role === "goal_continuation"
        ? t("goalContinuationIndicator")
        : t("goalUpdatedIndicator")
      : (activityPreview(event.message?.content ?? "") ?? t("agentFallback"));

  return (
    <Box py={activityRowVerticalPadding}>
      <Group gap="xs" wrap="nowrap" className={inlineControlClasses.root}>
        <Box
          aria-hidden="true"
          w={activityRowChevronSize}
          style={{ flexShrink: 0 }}
        />
        <Box c="dimmed" style={{ display: "inline-flex", flexShrink: 0 }}>
          {event.kind === "goal-control" ? (
            <IconTargetArrow aria-hidden="true" size={activityRowIconSize} />
          ) : (
            <IconBubble aria-hidden="true" size={activityRowIconSize} />
          )}
        </Box>
        <Text
          size={activityRowSummarySize}
          c="dimmed"
          fw={500}
          truncate
          flex={1}
          miw={0}
          className={inlineControlClasses.label}
        >
          {label}
        </Text>
      </Group>
    </Box>
  );
}
