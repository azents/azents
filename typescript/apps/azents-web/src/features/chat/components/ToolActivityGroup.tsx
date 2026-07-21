"use client";

import {
  Box,
  Collapse,
  Group,
  Loader,
  rem,
  Stack,
  Text,
  UnstyledButton,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconCheck, IconChevronRight } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ActivityMessageRow } from "./ActivityMessageRow";
import {
  activityRowChevronSize,
  activityRowIconSize,
  activityRowSummarySize,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import {
  chatChevronTransition,
  chatCollapseTransitionProps,
} from "./collapsiblePresentation";
import {
  formatElapsedDuration,
  startElapsedDurationTimer,
  visibleElapsedDurationSeconds,
} from "./elapsedDuration";
import { ProviderToolCallCard } from "./ProviderToolCallCard";
import { ReasoningActivityRow } from "./ReasoningActivityRow";
import { SkillLoadedActivityRow } from "./SkillLoadedActivityRow";
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
}

interface CategorySummary extends ActivityCategory {
  count: number;
}

const ACTIVITY_DURATION_VISIBILITY_THRESHOLD_SECONDS = 10;
const MAX_VISIBLE_CATEGORIES = 5;

function useVisibleElapsedDuration(
  startedAt: string | null,
  visibilityThresholdSeconds: number,
  enabled: boolean,
): number | null {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    return startElapsedDurationTimer(
      startedAt,
      () => setTick((tick) => tick + 1),
      (callback, delay) => window.setInterval(callback, delay),
      (timerId) => window.clearInterval(timerId),
    );
  }, [enabled, startedAt]);

  return enabled
    ? visibleElapsedDurationSeconds(
        startedAt,
        Date.now(),
        visibilityThresholdSeconds,
      )
    : null;
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
  if (event.kind === "reasoning") {
    return (
      <ReasoningActivityRow
        reasoningSummary={
          event.message?.reasoningSummary ?? event.message?.content ?? ""
        }
      />
    );
  }
  if (event.kind === "skill") {
    return (
      <SkillLoadedActivityRow
        content={event.message?.content ?? ""}
        name={event.message?.metadata?.name ?? null}
      />
    );
  }
  return <ActivityMessageRow event={event} />;
}

export function ToolActivityGroup({
  activity,
  authorizationAction,
  dimmed = false,
  active = false,
}: ToolActivityGroupProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const [opened, { close, open, toggle }] = useDisclosure(active);

  useEffect(() => {
    if (active) {
      open();
      return;
    }
    close();
  }, [active, close, open]);

  const hasDetails = activity.events.length > 0;
  const groupDurationSeconds = useVisibleElapsedDuration(
    activity.startedAt,
    ACTIVITY_DURATION_VISIBILITY_THRESHOLD_SECONDS,
    active && hasDetails,
  );
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
  const hiddenCategoryCount = Math.max(
    0,
    labels.length - MAX_VISIBLE_CATEGORIES,
  );
  const visibleLabels = labels.slice(0, MAX_VISIBLE_CATEGORIES);
  const summary = [
    ...visibleLabels,
    ...(hiddenCategoryCount > 0
      ? [t("overflowCategories", { count: hiddenCategoryCount })]
      : []),
  ].join(" · ");
  const groupDuration =
    groupDurationSeconds === null
      ? null
      : formatElapsedDuration(groupDurationSeconds);
  const accessibilitySummary = labels.join(" · ");
  const stateSummary = authorizationAction
    ? t("approvalNeeded")
    : active
      ? t("working")
      : t("complete");
  const ariaLabel = [
    t("title"),
    accessibilitySummary,
    stateSummary,
    groupDuration,
  ]
    .filter((value): value is string => value !== null && value.length > 0)
    .join(": ");

  const header = (
    <Stack gap={rem(2)} miw={0} w="100%">
      <Group
        gap={rem(6)}
        wrap="nowrap"
        miw={0}
        className={inlineControlClasses.root}
      >
        {hasDetails ? (
          <IconChevronRight
            aria-hidden="true"
            size={activityRowChevronSize}
            color="var(--mantine-color-dimmed)"
            style={{
              flexShrink: 0,
              transform: opened ? "rotate(90deg)" : "none",
              transition: chatChevronTransition,
            }}
          />
        ) : null}
        {!active ? (
          <IconCheck
            aria-label={t("complete")}
            size={activityRowIconSize}
            color="var(--mantine-color-dimmed)"
            style={{ flexShrink: 0 }}
          />
        ) : null}
        {summary.length > 0 ? (
          <Text
            size={activityRowSummarySize}
            c="dimmed"
            fw={500}
            truncate
            flex={1}
            miw={0}
            className={inlineControlClasses.label}
          >
            {summary}
          </Text>
        ) : null}
        {groupDuration !== null ? (
          <Text
            size={activityRowSummarySize}
            c="dimmed"
            ff="monospace"
            className={inlineControlClasses.label}
            style={{ flexShrink: 0, fontVariantNumeric: "tabular-nums" }}
          >
            {groupDuration}
          </Text>
        ) : null}
      </Group>
    </Stack>
  );

  return (
    <Box mb={rem(4)} opacity={dimmed ? 0.45 : 1} style={{ minWidth: 0 }}>
      <Group gap="xs" wrap="nowrap" data-tool-activity-id={activity.id}>
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

      <Collapse
        expanded={opened}
        keepMounted={false}
        {...chatCollapseTransitionProps}
      >
        <Stack gap={0} mt={rem(2)} pl="xs">
          {activity.events.map((event) => (
            <Box key={event.id}>{eventDetail(event)}</Box>
          ))}
          {active ? (
            <Box
              aria-label="Live activity is running"
              h={rem(16)}
              pl={rem(activityRowChevronSize + 6)}
              role="status"
              style={{ alignItems: "center", display: "inline-flex" }}
            >
              <Loader
                aria-hidden="true"
                color="var(--mantine-color-dimmed)"
                size={rem(activityRowIconSize)}
              />
            </Box>
          ) : null}
        </Stack>
      </Collapse>
    </Box>
  );
}
