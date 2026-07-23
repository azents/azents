"use client";

import { Box } from "@mantine/core";
import { AgentSessionHeader } from "@/features/agents/components/AgentSessionHeader";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { SessionChannels } from "./components/SessionChannels";
import { useSessionChannelsContainer } from "./containers/useSessionChannelsContainer";
import type { SessionChannelsContainerOutput } from "./containers/useSessionChannelsContainer";

function SessionChannelsWithHeader(
  props: SessionChannelsContainerOutput,
): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      {props.state.type === "LOADED" ? (
        <AgentSessionHeader
          handle={props.handle}
          agent={props.agent}
          sessionId={props.sessionId}
          session={props.state.session}
        />
      ) : (
        <AgentSessionHeader
          handle={props.handle}
          agent={props.agent}
          sessionId={props.sessionId}
        />
      )}
      <SessionChannels {...props} />
    </Box>
  );
}

export const SessionChannelsPage = createReactContainer(
  "SessionChannelsPage",
  useSessionChannelsContainer,
  SessionChannelsWithHeader,
);
