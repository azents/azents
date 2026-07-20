"use client";

import { Component } from "react";
import { useSubscriptionUsageContainer } from "@/features/llm-settings/containers/useSubscriptionUsageContainer";
import { ComposerSubscriptionUsagePopover } from "../components/ComposerSubscriptionUsage";
import type { SubscriptionUsageState } from "@/features/llm-settings/subscriptionUsage";
import type { ReactNode } from "react";

interface ComposerSubscriptionUsagePopoverContainerProps {
  compact: boolean;
  handle: string;
  integrationId: string;
  provider: string;
}

interface ComposerUsageErrorBoundaryProps {
  children: ReactNode;
  fallback: (reset: () => void) => ReactNode;
  resetKey: string;
}

interface ComposerUsageErrorBoundaryState {
  failed: boolean;
}

class ComposerUsageErrorBoundary extends Component<
  ComposerUsageErrorBoundaryProps,
  ComposerUsageErrorBoundaryState
> {
  public state: ComposerUsageErrorBoundaryState = { failed: false };

  public static getDerivedStateFromError(): ComposerUsageErrorBoundaryState {
    return { failed: true };
  }

  public componentDidUpdate(
    previousProps: ComposerUsageErrorBoundaryProps,
  ): void {
    if (this.state.failed && previousProps.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  private readonly reset = (): void => {
    this.setState({ failed: false });
  };

  public render(): ReactNode {
    if (this.state.failed) {
      return this.props.fallback(this.reset);
    }
    return this.props.children;
  }
}

function composerUsageBoundaryResetKey(state: SubscriptionUsageState): string {
  switch (state.type) {
    case "AVAILABLE":
    case "EXTERNAL":
    case "STALE_ERROR":
      return `${state.type}:${state.snapshot.fetched_at}`;
    case "UNAVAILABLE":
      return `${state.type}:${state.reason ?? "request_failed"}`;
    case "IDLE":
    case "DISABLED":
    case "LOADING":
      return state.type;
  }
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
  const fallbackState: SubscriptionUsageState = {
    type: "UNAVAILABLE",
    reason: null,
    retryable: true,
  };
  return (
    <ComposerUsageErrorBoundary
      fallback={(reset) => (
        <ComposerSubscriptionUsagePopover
          compact={compact}
          onRefresh={async () => {
            reset();
            await onRefresh();
          }}
          state={fallbackState}
        />
      )}
      resetKey={`${integrationId}:${composerUsageBoundaryResetKey(state)}`}
    >
      <ComposerSubscriptionUsagePopover
        compact={compact}
        onRefresh={onRefresh}
        state={state}
      />
    </ComposerUsageErrorBoundary>
  );
}
