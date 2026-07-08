"use client";

/** Agent settings hub page entry. */

import { rem } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSettingsHub } from "./components/AgentSettingsHub";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsHubContainerProps {
  handle: string;
  agent: AgentResponse;
}

function useAgentSettingsHubContainer(
  props: AgentSettingsHubContainerProps,
): AgentSettingsHubContainerProps {
  return props;
}

function AgentSettingsHubWithHeader({
  handle,
  agent,
}: AgentSettingsHubContainerProps): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={handle}
      agent={agent}
      backTarget="agent"
      backMaxWidth={rem(860)}
    >
      <AgentSettingsHub handle={handle} agent={agent} />
    </AgentSettingsLayout>
  );
}

export const AgentSettingsHubPage = createReactContainer(
  "AgentSettingsHubPage",
  useAgentSettingsHubContainer,
  AgentSettingsHubWithHeader,
);
