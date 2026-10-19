"use client";

import { Box, Loader, rem, Text } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useToolActivityGroup } from "../containers/useToolActivityGroup";
import { ActivityEventList } from "./ActivityEventList";
import { ActivityRow } from "./ActivityRow";
import {
  activityRowIconSize,
  activityRowSummarySize,
} from "./activityRowPresentation";
import inlineControlClasses from "./ChatInlineControl.module.css";
import { ChatTimelineItem } from "./ChatTimelineItem";
import { formatElapsedDuration } from "./elapsedDuration";
import type { ToolActivityGroupViewProps } from "../containers/useToolActivityGroup";
import type {
  ActivityCategory,
  ActivityEvent,
} from "@azents/session-core/toolActivityPresentation";

interface CategorySummary extends ActivityCategory {
  count: number;
}
const MAX_VISIBLE_CATEGORIES = 5;

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
    case "browser":
      return t("categoryBrowser");
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
    case "wait":
      return t("categoryWait");
    case "git":
      return t("categoryGit");
    case "schedule":
      return t("categorySchedule");
    case "routine":
      return t("categoryRoutine");
    case "web-service":
      return t("categoryWebService");
    case "channel":
      return t("categoryChannel");
    case "other":
      return t("categoryOther");
    default:
      return category.label;
  }
}

export function ToolActivityGroupView({
  activity,
  authorizationAction,
  dimmed = false,
  active = false,
  opened,
  toggle,
  groupDurationSeconds,
}: ToolActivityGroupViewProps): React.ReactElement {
  const t = useTranslations("chat.toolActivity");
  const hasDetails = activity.events.length > 0;
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
    categoryLabels.length - MAX_VISIBLE_CATEGORIES,
  );
  const summary = [
    ...categoryLabels.slice(0, MAX_VISIBLE_CATEGORIES),
    ...(hiddenCategoryCount > 0
      ? [t("overflowCategories", { count: hiddenCategoryCount })]
      : []),
    ...(failedCount > 0 ? [t("failedCount", { count: failedCount })] : []),
  ].join(" · ");
  const groupDuration =
    groupDurationSeconds === null
      ? null
      : formatElapsedDuration(groupDurationSeconds);
  const stateSummary = authorizationAction
    ? t("approvalNeeded")
    : active
      ? t("working")
      : t("complete");
  const ariaLabel = [
    t("title"),
    labels.join(" · "),
    stateSummary,
    groupDuration,
  ]
    .filter((value): value is string => value !== null && value.length > 0)
    .join(": ");
  return (
    <ChatTimelineItem kind="activity" opacity={dimmed ? 0.45 : 1}>
      <Box data-tool-activity-id={activity.id}>
        <ActivityRow
          ariaLabel={ariaLabel}
          primary={summary}
          disclosure={{ opened, onToggle: toggle }}
          action={authorizationAction}
          icon={
            active && hasDetails ? (
              <Box aria-label="Live activity is running" role="status">
                <Loader
                  aria-hidden="true"
                  color="var(--mantine-color-dimmed)"
                  size={rem(activityRowIconSize)}
                />
              </Box>
            ) : !active ? (
              <IconCheck
                aria-label={t("complete")}
                size={activityRowIconSize}
              />
            ) : null
          }
          status={
            groupDuration === null ? null : (
              <Text
                size={activityRowSummarySize}
                c="dimmed"
                ff="monospace"
                className={inlineControlClasses.label}
                style={{ flexShrink: 0, fontVariantNumeric: "tabular-nums" }}
              >
                {groupDuration}
              </Text>
            )
          }
          detail={
            hasDetails ? <ActivityEventList events={activity.events} /> : null
          }
        />
      </Box>
    </ChatTimelineItem>
  );
}

export const ToolActivityGroup = createReactContainer(
  "ToolActivityGroup",
  useToolActivityGroup,
  ToolActivityGroupView,
);
