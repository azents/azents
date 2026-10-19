"use client";

import { IconRobot } from "@tabler/icons-react";
import { ActivityRow } from "./ActivityRow";
import { activityRowIconSize } from "./activityRowPresentation";
import { ChatDetailPanel } from "./ChatDetailPanel";
import { ChatTimelineItem } from "./ChatTimelineItem";
import { MarkdownContent } from "./MarkdownContent";

interface AgentMessageDisclosureProps {
  title: string;
  titleTooltip?: string;
  content: string;
  actions?: React.ReactNode;
  opacity?: number;
  icon?: React.ReactNode;
}

export function AgentMessageDisclosure({
  title,
  titleTooltip = title,
  content,
  actions = null,
  opacity = 1,
  icon = null,
}: AgentMessageDisclosureProps): React.ReactElement {
  return (
    <ChatTimelineItem kind="activity" opacity={opacity}>
      <ActivityRow
        ariaLabel={titleTooltip}
        primary={title}
        primaryTooltip={titleTooltip}
        icon={
          icon ?? <IconRobot aria-hidden="true" size={activityRowIconSize} />
        }
        detail={
          <ChatDetailPanel>
            <MarkdownContent>{content}</MarkdownContent>
            {actions}
          </ChatDetailPanel>
        }
      />
    </ChatTimelineItem>
  );
}
