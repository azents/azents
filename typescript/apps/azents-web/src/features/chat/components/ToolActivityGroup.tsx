"use client";

import {
  Box,
  Collapse,
  Group,
  Loader,
  rem,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure, useElementSize } from "@mantine/hooks";
import {
  IconAlertCircle,
  IconChevronRight,
  IconTool,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
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
}: ToolActivityGroupProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const [opened, { toggle }] = useDisclosure(false);
  const { ref, width } = useElementSize();
  const categories = categorySummaries(activity.events);
  const running = activity.events.some((event) => event.status === "running");
  const failed = activity.events.some((event) => event.status === "failed");
  const labels = categories.map((category) => {
    const label = categoryLabel(category, t);
    return category.count > 1 ? `${label} ${category.count}` : label;
  });
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
  const stateSummary = failed
    ? t("failed")
    : authorizationAction
      ? t("approvalNeeded")
      : running
        ? t("working")
        : "";
  const ariaLabel = [t("title"), accessibilitySummary, stateSummary]
    .filter((value) => value.length > 0)
    .join(": ");

  return (
    <Box mb="xs" opacity={dimmed ? 0.45 : 1} style={{ minWidth: 0 }}>
      <Group
        gap="xs"
        wrap="nowrap"
        ref={ref}
        data-tool-activity-id={activity.id}
      >
        <UnstyledButton
          flex={1}
          miw={0}
          onClick={toggle}
          aria-expanded={opened}
          aria-label={ariaLabel}
        >
          <Group gap="xs" wrap="nowrap" miw={0}>
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
            <ThemeIcon size={rem(20)} variant="transparent" color="gray">
              <IconTool size={rem(14)} />
            </ThemeIcon>
            <Text size="xs" fw={550} style={{ flexShrink: 0 }}>
              {t("title")}
            </Text>
            {running && !failed && !authorizationAction ? (
              <Group gap={rem(4)} wrap="nowrap" style={{ flexShrink: 0 }}>
                <Loader size={rem(12)} color="gray" />
                <Text size="xs" c="dimmed">
                  {t("working")}
                </Text>
              </Group>
            ) : null}
            {summary.length > 0 ? (
              <Text size="xs" c="dimmed" truncate>
                {summary}
              </Text>
            ) : null}
            {failed ? (
              <IconAlertCircle
                aria-label={t("failed")}
                size={rem(15)}
                color="var(--mantine-color-red-6)"
                style={{ flexShrink: 0 }}
              />
            ) : null}
          </Group>
        </UnstyledButton>
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
