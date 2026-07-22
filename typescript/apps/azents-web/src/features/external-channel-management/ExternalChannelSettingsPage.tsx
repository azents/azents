"use client";

import { AgentSettingsLayout } from "@/features/agents/components/AgentSettingsLayout";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { ExternalChannelSettings } from "./components/ExternalChannelSettings";
import { useExternalChannelSettingsContainer } from "./containers/useExternalChannelSettingsContainer";
import type { ExternalChannelSettingsContainerOutput } from "./containers/useExternalChannelSettingsContainer";

function ExternalChannelSettingsWithHeader(
  props: ExternalChannelSettingsContainerOutput,
): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={props.handle}
      agent={props.agent}
      backTarget="settings"
    >
      <ExternalChannelSettings {...props} />
    </AgentSettingsLayout>
  );
}

export const ExternalChannelSettingsPage = createReactContainer(
  "ExternalChannelSettingsPage",
  useExternalChannelSettingsContainer,
  ExternalChannelSettingsWithHeader,
);
