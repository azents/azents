"use client";

import { Box, Collapse, Group, rem, Text, UnstyledButton } from "@mantine/core";
import {
  IconBook,
  IconBubble,
  IconChevronRight,
  IconTargetArrow,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  activityRowChevronSize,
  activityRowDetailInset,
  activityRowIconSize,
  activityRowSummarySize,
  activityRowVerticalPadding,
} from "./activityRowPresentation";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import { MarkdownContent } from "./MarkdownContent";
import type { ActivityEvent } from "../toolActivityPresentation";
import type { ReactElement } from "react";

interface ActivityMessageRowProps {
  event: ActivityEvent;
}

function stripFrontmatter(content: string): string {
  const frontmatter = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/u.exec(
    content.replace(/^\uFEFF/u, ""),
  );
  if (frontmatter === null || frontmatter.index !== 0) {
    return content;
  }
  return content.slice(frontmatter[0].length).trimStart();
}

function activityPreview(content: string): string | null {
  const preview = content
    .replace(/<!--[\s\S]*?-->/gu, "")
    .split(/\r?\n/u)
    .map((line) => line.trim())
    .find((line) => line.length > 0);
  return preview && preview.length > 0 ? preview : null;
}

function messageDetail(event: ActivityEvent): string | null {
  const message = event.message;
  if (message === null) {
    return null;
  }
  switch (event.kind) {
    case "reasoning":
      return message.reasoningSummary ?? message.content;
    case "skill":
      return stripFrontmatter(message.content ?? "");
    case "goal-control":
    case "other":
    case "tool":
      return null;
  }
}

function messageLabel(
  event: ActivityEvent,
  detail: string | null,
  t: ReturnType<typeof useTranslations<"chat">>,
): string {
  const message = event.message;
  switch (event.kind) {
    case "reasoning":
      return activityPreview(detail ?? "") ?? t("thinkingLabel");
    case "skill":
      return t("skillLoaded.title", {
        name: message?.metadata?.name || t("skillLoaded.unknownSkill"),
      });
    case "goal-control":
      return message?.role === "goal_continuation"
        ? t("goalContinuationIndicator")
        : t("goalUpdatedIndicator");
    case "other":
      return activityPreview(message?.content ?? "") ?? t("agentFallback");
    case "tool":
      return "";
  }
}

function messageIcon(event: ActivityEvent): ReactElement {
  switch (event.kind) {
    case "skill":
      return <IconBook aria-hidden="true" size={activityRowIconSize} />;
    case "goal-control":
      return <IconTargetArrow aria-hidden="true" size={activityRowIconSize} />;
    case "reasoning":
    case "other":
    case "tool":
      return <IconBubble aria-hidden="true" size={activityRowIconSize} />;
  }
}

export function ActivityMessageRow({
  event,
}: ActivityMessageRowProps): ReactElement | null {
  const t = useTranslations("chat");
  const [opened, setOpened] = useState(false);
  const detail = messageDetail(event);
  const canExpand = detail !== null && detail.trim().length > 0;
  const label = messageLabel(event, detail, t);

  return (
    <Box py={activityRowVerticalPadding}>
      <UnstyledButton
        w="100%"
        onClick={() => setOpened((value) => !value)}
        aria-expanded={opened}
        aria-label={label}
        disabled={!canExpand}
      >
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <IconChevronRight
            aria-hidden="true"
            size={activityRowChevronSize}
            color="var(--mantine-color-dimmed)"
            style={{
              flexShrink: 0,
              marginTop: rem(1),
              opacity: canExpand ? 1 : 0,
              transform: opened ? "rotate(90deg)" : "none",
              transition: chatChevronTransition,
            }}
          />
          <Box c="dimmed" style={{ flexShrink: 0, marginTop: rem(1) }}>
            {messageIcon(event)}
          </Box>
          <Text
            size={activityRowSummarySize}
            c="dimmed"
            fw={500}
            truncate
            flex={1}
            miw={0}
          >
            {label}
          </Text>
        </Group>
      </UnstyledButton>
      {detail !== null ? (
        <Collapse
          expanded={opened}
          keepMounted={false}
          {...chatCollapseTransitionProps}
        >
          <Box pl={activityRowDetailInset} pr="xs" pt="xs">
            <MarkdownContent>{detail}</MarkdownContent>
          </Box>
        </Collapse>
      ) : null}
    </Box>
  );
}
