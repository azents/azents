import { rem } from "@mantine/core";
import { chatCollapsibleChevronSize } from "./collapsiblePresentation";
import type { DataAttributes, ScrollAreaProps } from "@mantine/core";

type ScrollViewportProps = NonNullable<ScrollAreaProps["viewportProps"]> &
  DataAttributes;

const activityDetailScrollViewportProps: ScrollViewportProps = {
  "data-activity-detail-scroll-viewport": true,
};

export const activityRowBorder =
  "1px solid var(--mantine-color-default-border)";
export const chatScrollOverscrollBehavior = "contain" as const;
export const chatScrollViewportProps: ScrollViewportProps = {
  "data-chat-scroll-viewport": true,
};
export const activityDetailScrollAreaProps = {
  overscrollBehavior: chatScrollOverscrollBehavior,
  viewportProps: activityDetailScrollViewportProps,
} satisfies Pick<ScrollAreaProps, "overscrollBehavior" | "viewportProps">;
export const activityRowChevronSize = chatCollapsibleChevronSize;
export const activityRowDetailInset = rem(28);
export const activityDetailScrollbarSize = rem(6);
export const activityRowIconSize = 14;
export const activityRowSummarySize = "xs" as const;
export const activityRowVerticalPadding = rem(2);
