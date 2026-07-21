"use client";

import { IconBubble, IconTargetArrow } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { ActivityRow } from "./ActivityRow";
import { activityRowIconSize } from "./activityRowPresentation";
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
    <ActivityRow
      ariaLabel={label}
      icon={
        event.kind === "goal-control" ? (
          <IconTargetArrow aria-hidden="true" size={activityRowIconSize} />
        ) : (
          <IconBubble aria-hidden="true" size={activityRowIconSize} />
        )
      }
      primary={label}
    />
  );
}
