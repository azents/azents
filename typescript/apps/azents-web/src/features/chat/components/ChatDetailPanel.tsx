import { Paper, ScrollArea } from "@mantine/core";
import {
  activityDetailScrollAreaProps,
  activityDetailScrollbarSize,
} from "../../../shared/chat-presentation/components/activityRowPresentation";
import { chatContentMaxWidth } from "./ChatTimelineItem";
import type { ReactElement, ReactNode } from "react";

/** Standard bordered detail surface for transcript disclosures and notices. */
export function ChatDetailPanel({
  children,
  maxHeight,
}: {
  children: ReactNode;
  maxHeight?: string | null;
}): ReactElement {
  return (
    <Paper
      data-chat-detail-panel
      withBorder
      radius="md"
      p="sm"
      maw={chatContentMaxWidth}
      bg="var(--mantine-color-body)"
      style={{ minWidth: 0, overflow: "hidden", overflowWrap: "anywhere" }}
    >
      {maxHeight ? (
        <ScrollArea.Autosize
          mah={maxHeight}
          scrollbars="y"
          scrollbarSize={activityDetailScrollbarSize}
          {...activityDetailScrollAreaProps}
        >
          {children}
        </ScrollArea.Autosize>
      ) : (
        children
      )}
    </Paper>
  );
}
