"use client";

import {
  Box,
  Collapse,
  Group,
  rem,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure, useElementSize } from "@mantine/hooks";
import { IconCheck, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { AgentRunIndicator } from "./AgentRunIndicator";
import inlineControlClasses from "./ChatInlineControl.module.css";
import { CompactionDivider } from "./CompactionDivider";
import { MessageBubble } from "./MessageBubble";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ToolCallCard } from "./ToolCallCard";
import type {
  ActivityCategory,
  ActivityEvent,
  ToolActivityGroup as ToolActivityGroupModel,
} from "../toolActivityPresentation";
import type { ReactNode } from "react";

interface ToolActivityGroupProps {
  activity: ToolActivityGroupModel;
  authorizationAction?: ReactNode;
  dimmed?: boolean;
  active?: boolean;
  modelCallStartedAt?: string | null;
}

interface CategorySummary extends ActivityCategory {
  count: number;
}

function categorySummaries(events: ActivityEvent[]): CategorySummary[] {
  const categories: CategorySummary[] = [];
  for (const event of events) {
    if (event.category === null) {
      continue;
    }
    const previous = categories.find(
      (category) => category.key === event.category?.key,
    );
    if (previous) {
      previous.count += 1;
      continue;
    }
    categories.push({ ...event.category, count: 1 });
  }
  return categories;
}

function categoryLabel(
  category: CategorySummary,
  t: ReturnType<typeof useTranslations<"chat.toolActivity">>,
): string {
  switch (category.key) {
    case "reasoning":
      return t("categoryReasoning");
    case "skill":
      return t("categorySkill");
    case "explore":
      return t("categoryExplore");
    case "shell":
      return t("categoryShell");
    case "edit":
      return t("categoryEdit");
    case "file":
      return t("categoryFile");
    case "image":
      return t("categoryImage");
    case "memory":
      return t("categoryMemory");
    case "organize":
      return t("categoryOrganize");
    case "subagent":
      return t("categorySubagent");
    case "other":
      return t("categoryOther");
    default:
      return category.label;
  }
}

function eventDetail(event: ActivityEvent): React.ReactElement | null {
  if (event.kind === "tool" && event.toolCall) {
    return event.toolCall.type === "client" ? (
      <ToolCallCard toolCall={event.toolCall.toolCall} />
    ) : (
      <ProviderToolCallCard toolCall={event.toolCall.toolCall} />
    );
  }
  if (event.kind === "compaction" && event.message?.content) {
    return <CompactionDivider content={event.message.content} />;
  }
  if (event.message) {
    return <MessageBubble message={event.message} />;
  }
  return null;
}

export function ToolActivityGroup({
  activity,
  authorizationAction,
  dimmed = false,
  active = false,
  modelCallStartedAt = null,
}: ToolActivityGroupProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const [opened, { toggle }] = useDisclosure(false);
  const { ref, width } = useElementSize();
  const categories = categorySummaries(activity.events);
  const failedCount = activity.events.filter(
    (event) => event.status === "failed",
  ).length;
  const categoryLabels = categories.map((category) => {
    const label = categoryLabel(category, t);
    return category.count > 1 ? `${label} ${category.count}` : label;
  });
  const labels = [
    ...categoryLabels,
    ...(failedCount > 0 ? [t("failedCount", { count: failedCount })] : []),
  ];
  const maxVisibleCategories = Math.max(1, Math.floor(width / 96));
  const hiddenCategoryCount = Math.max(0, labels.length - maxVisibleCategories);
  const visibleLabels = labels.slice(0, maxVisibleCategories);
  const summary = [
    ...visibleLabels,
    ...(hiddenCategoryCount > 0
      ? [t("overflowCategories", { count: hiddenCategoryCount })]
      : []),
  ].join(" · ");
  const accessibilitySummary = labels.join(" · ");
  const stateSummary = authorizationAction
    ? t("approvalNeeded")
    : active
      ? t("working")
      : t("complete");
  const ariaLabel = [t("title"), accessibilitySummary, stateSummary]
    .filter((value) => value.length > 0)
    .join(": ");
  const hasDetails = activity.events.length > 0;

  const header = (
    <Group
      gap={rem(6)}
      wrap="nowrap"
      miw={0}
      className={inlineControlClasses.root}
    >
      {hasDetails ? (
        <IconChevronRight
          aria-hidden="true"
          size={rem(14)}
          color="var(--mantine-color-dimmed)"
          style={{
            flexShrink: 0,
            transform: opened ? "rotate(90deg)" : "none",
            transition: "transform 120ms ease",
          }}
        />
      ) : null}
      {active ? (
        <AgentRunIndicator modelCallStartedAt={modelCallStartedAt} />
      ) : (
        <IconCheck
          aria-label={t("complete")}
          size={rem(14)}
          color="var(--mantine-color-dimmed)"
          style={{ flexShrink: 0 }}
        />
      )}
      {summary.length > 0 ? (
        <Text size="xs" c="dimmed" fw={500} truncate>
          {summary}
        </Text>
      ) : null}
    </Group>
  );

  return (
    <Box mb="xs" opacity={dimmed ? 0.45 : 1} style={{ minWidth: 0 }}>
      <Group
        gap="xs"
        wrap="nowrap"
        ref={ref}
        data-tool-activity-id={activity.id}
      >
        {hasDetails ? (
          <UnstyledButton
            flex={1}
            miw={0}
            onClick={toggle}
            aria-expanded={opened}
            aria-label={ariaLabel}
          >
            {header}
          </UnstyledButton>
        ) : (
          <Box flex={1} miw={0} aria-label={ariaLabel}>
            {header}
          </Box>
        )}
        {authorizationAction}
      </Group>

      <Collapse expanded={opened}>
        <Stack gap="xs" mt="xs" pl="md">
          {activity.events.map((event) => (
            <Box key={event.id}>{eventDetail(event)}</Box>
          ))}
        </Stack>
      </Collapse>
    </Box>
  );
}
