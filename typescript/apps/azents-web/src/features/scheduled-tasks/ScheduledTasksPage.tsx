"use client";

import { Box } from "@mantine/core";
import { AgentSessionHeader } from "@/shared/agent-session/AgentSessionHeader";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ScheduledTasks } from "./components/ScheduledTasks";
import { useScheduledTasksContainer } from "./containers/useScheduledTasksContainer";
import type { ScheduledTasksContainerOutput } from "./containers/useScheduledTasksContainer";

function ScheduledTasksWithHeader(
  props: ScheduledTasksContainerOutput,
): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader
        handle={props.handle}
        agent={props.agent}
        sessionId={props.sessionId}
        session={props.session}
        onUpdateTitle={props.onUpdateTitle}
      />
      <ScheduledTasks {...props} />
    </Box>
  );
}

export const ScheduledTasksPage = createReactContainer(
  "ScheduledTasksPage",
  useScheduledTasksContainer,
  ScheduledTasksWithHeader,
);
