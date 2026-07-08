"use client";

/**
 * Agent settings page entry.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentSettings } from "./components/AgentSettings";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import { useAgentSettingsContainer } from "./containers/useAgentSettingsContainer";
import type { AgentSettingsContainerOutput } from "./containers/useAgentSettingsContainer";

function AgentSettingsWithHeader(
  props: AgentSettingsContainerOutput,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentSettings {...props} />
    </AgentSettingsLayout>
  );
}

export const AgentSettingsPage = createReactContainer(
  "AgentSettingsPage",
  useAgentSettingsContainer,
  AgentSettingsWithHeader,
);
