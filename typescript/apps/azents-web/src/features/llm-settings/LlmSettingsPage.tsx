"use client";

/**
 * LLM Settings page entry point.
 *
 * Connects logic (container) and UI (component) with createReactContainer.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { LlmSettings } from "./components/LlmSettings";
import { SubscriptionUsageContainer } from "./containers/SubscriptionUsageContainer";
import { useLlmSettingsContainer } from "./containers/useLlmSettingsContainer";
import type { LlmSettingsContainerOutput } from "./containers/useLlmSettingsContainer";

function ConnectedLlmSettings(
  props: LlmSettingsContainerOutput,
): React.ReactElement {
  return (
    <LlmSettings
      {...props}
      renderSubscriptionUsage={(integration) => (
        <SubscriptionUsageContainer
          enabled={integration.enabled}
          handle={props.handle}
          integrationId={integration.id}
          provider={integration.provider}
        />
      )}
    />
  );
}

export const LlmSettingsPage = createReactContainer(
  "LlmSettingsPage",
  useLlmSettingsContainer,
  ConnectedLlmSettings,
);
