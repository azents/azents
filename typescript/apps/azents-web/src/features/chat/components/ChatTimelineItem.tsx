import { Box, rem } from "@mantine/core";
import type { ReactElement, ReactNode } from "react";

export const chatContentMaxWidth = rem(720);
export const chatHumanMessageMaxWidth = "75%";

/** Owns outer transcript spacing; nested content never adds a second item gap. */
export function ChatTimelineItem({
  children,
  kind = "message",
  opacity = 1,
}: {
  children: ReactNode;
  kind?: "message" | "activity" | "boundary";
  opacity?: number;
}): ReactElement {
  return (
    <Box
      data-chat-item={kind}
      mb={kind === "activity" ? rem(4) : "md"}
      w="100%"
      miw={0}
      opacity={opacity}
    >
      {children}
    </Box>
  );
}
