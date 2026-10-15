"use client";

import { useDisclosure } from "@mantine/hooks";
import { useEffect, useState } from "react";
import {
  startElapsedDurationTimer,
  visibleElapsedDurationSeconds,
} from "../components/elapsedDuration";
import type { ToolActivityGroup as ToolActivityGroupModel } from "@azents/session-core/toolActivityPresentation";
import type { ReactNode } from "react";

export interface ToolActivityGroupProps {
  activity: ToolActivityGroupModel;
  authorizationAction?: ReactNode;
  dimmed?: boolean;
  active?: boolean;
}
export interface ToolActivityGroupViewProps extends ToolActivityGroupProps {
  opened: boolean;
  toggle: () => void;
  groupDurationSeconds: number | null;
}
export function useToolActivityGroup(
  props: ToolActivityGroupProps,
): ToolActivityGroupViewProps {
  const { activity, active = false } = props;
  const [opened, { close, open, toggle }] = useDisclosure(active);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (active) {
      open();
      return;
    }
    close();
  }, [active, close, open]);
  const enabled = active && activity.events.length > 0;
  useEffect(() => {
    if (!enabled) {
      return;
    }
    return startElapsedDurationTimer(
      activity.startedAt,
      () => setTick((tick) => tick + 1),
      (callback, delay) => window.setInterval(callback, delay),
      (timerId) => window.clearInterval(timerId),
    );
  }, [enabled, activity.startedAt]);
  return {
    ...props,
    opened,
    toggle,
    groupDurationSeconds: enabled
      ? visibleElapsedDurationSeconds(activity.startedAt, Date.now(), 10)
      : null,
  };
}
