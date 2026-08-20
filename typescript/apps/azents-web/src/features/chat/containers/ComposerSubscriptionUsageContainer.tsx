"use client";

import { useSubscriptionUsageContainer } from "@/features/llm-settings/containers/useSubscriptionUsageContainer";
import { ComposerSubscriptionUsagePopoverWithBoundary } from "../components/ComposerSubscriptionUsage";

interface ComposerSubscriptionUsagePopoverContainerProps {
  compact: boolean;
  handle: string;
  integrationId: string;
  provider: string;
}

export function ComposerSubscriptionUsagePopoverContainer({
  compact,
  handle,
  integrationId,
  provider,
}: ComposerSubscriptionUsagePopoverContainerProps): React.ReactElement | null {
  const { state, onRefresh } = useSubscriptionUsageContainer({
    enabled: true,
    handle,
    integrationId,
    provider,
  });
  return (
    <ComposerSubscriptionUsagePopoverWithBoundary
      compact={compact}
      onRefresh={onRefresh}
      resetKey={integrationId}
      state={state}
    />
  );
}
