"use client";

import { useDisclosure } from "@mantine/hooks";
import type { ActionExecutionProjection } from "@azents/session-core/types";
import type { useTranslations } from "next-intl";

export interface CleanupActionDetailsProps {
  actionExecution: ActionExecutionProjection;
  t: ReturnType<typeof useTranslations<"chat.actionExecution">>;
}
export function useCleanupActionDetails(
  props: CleanupActionDetailsProps,
): CleanupActionDetailsProps & {
  detailsOpened: boolean;
  close: () => void;
  toggle: () => void;
} {
  const [detailsOpened, { close, toggle }] = useDisclosure(false);
  return { ...props, detailsOpened, close, toggle };
}
