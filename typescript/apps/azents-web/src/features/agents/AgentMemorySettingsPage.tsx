"use client";

/** Agent Memory settings page entry. */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { AgentMemorySettings } from "./components/AgentMemorySettings";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import { useAgentMemorySettingsContainer } from "./containers/useAgentMemorySettingsContainer";
import type { AgentMemorySettingsContainerOutput } from "./containers/useAgentMemorySettingsContainer";

function AgentMemorySettingsWithHeader(
  props: AgentMemorySettingsContainerOutput,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <AgentMemorySettings {...props} />
    </AgentSettingsLayout>
  );
}

export const AgentMemorySettingsPage = createReactContainer(
  "AgentMemorySettingsPage",
  useAgentMemorySettingsContainer,
  AgentMemorySettingsWithHeader,
);
