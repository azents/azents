"use client";

import { Component } from "react";
import { useSubscriptionUsageContainer } from "@/features/llm-settings/containers/useSubscriptionUsageContainer";
import {
  ComposerSubscriptionUsageDetails,
  ComposerSubscriptionUsageIndicator,
} from "../components/ComposerSubscriptionUsage";
import type { SubscriptionUsageState } from "@/features/llm-settings/subscriptionUsage";
import type { ReactNode } from "react";

interface ComposerSubscriptionUsageBaseProps {
  handle: string;
  integrationId: string;
  provider: string;
}

interface ComposerSubscriptionUsageIndicatorContainerProps extends ComposerSubscriptionUsageBaseProps {
  compact: boolean;
  onOpen: () => void;
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

export function ComposerSubscriptionUsageIndicatorContainer({
  compact,
  handle,
  integrationId,
  onOpen,
  provider,
}: ComposerSubscriptionUsageIndicatorContainerProps): React.ReactElement | null {
  const { state } = useSubscriptionUsageContainer({
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
      fallback={() => (
        <ComposerSubscriptionUsageIndicator
          compact={compact}
          onOpen={onOpen}
          state={fallbackState}
        />
      )}
      resetKey={`${integrationId}:${composerUsageBoundaryResetKey(state)}`}
    >
      <ComposerSubscriptionUsageIndicator
        compact={compact}
        onOpen={onOpen}
        state={state}
      />
    </ComposerUsageErrorBoundary>
  );
}

export function ComposerSubscriptionUsageDetailsContainer({
  handle,
  integrationId,
  provider,
}: ComposerSubscriptionUsageBaseProps): React.ReactElement | null {
  const { state, onRefresh } = useSubscriptionUsageContainer({
    enabled: true,
    handle,
    integrationId,
    provider,
  });
  return (
    <ComposerUsageErrorBoundary
      fallback={(reset) => (
        <ComposerSubscriptionUsageDetails
          state={{ type: "UNAVAILABLE", reason: null, retryable: true }}
          onRefresh={async () => {
            reset();
            await onRefresh();
          }}
        />
      )}
      resetKey={`${integrationId}:${composerUsageBoundaryResetKey(state)}`}
    >
      <ComposerSubscriptionUsageDetails state={state} onRefresh={onRefresh} />
    </ComposerUsageErrorBoundary>
  );
}
