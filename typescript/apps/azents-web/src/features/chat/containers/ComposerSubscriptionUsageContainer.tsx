"use client";

import { ComposerSubscriptionUsagePopoverWithBoundary } from "@/shared/subscription-usage/ComposerSubscriptionUsage";
import { useSubscriptionUsageContainer } from "./useSubscriptionUsageContainer";

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
