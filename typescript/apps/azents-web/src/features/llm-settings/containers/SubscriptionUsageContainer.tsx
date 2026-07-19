"use client";

import { Component } from "react";
import { SubscriptionUsageSummary } from "../components/SubscriptionUsageSummary";
import { useSubscriptionUsageContainer } from "./useSubscriptionUsageContainer";
import type { SubscriptionUsageState } from "../subscriptionUsage";
import type { SubscriptionUsageContainerProps } from "./useSubscriptionUsageContainer";
import type { ReactNode } from "react";

interface UsageErrorBoundaryProps {
  children: ReactNode;
  fallback: (reset: () => void) => ReactNode;
  resetKey: string;
}

interface UsageErrorBoundaryState {
  failed: boolean;
}

class UsageErrorBoundary extends Component<
  UsageErrorBoundaryProps,
  UsageErrorBoundaryState
> {
  public state: UsageErrorBoundaryState = { failed: false };

  public static getDerivedStateFromError(): UsageErrorBoundaryState {
    return { failed: true };
  }

  public componentDidUpdate(previousProps: UsageErrorBoundaryProps): void {
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

function usageBoundaryResetKey(state: SubscriptionUsageState): string {
  switch (state.type) {
    case "AVAILABLE":
    case "EXTERNAL":
      return `${state.type}:${state.snapshot.fetched_at}`;
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

export function SubscriptionUsageContainer(
  props: SubscriptionUsageContainerProps,
): React.ReactElement | null {
  const { state, onRefresh } = useSubscriptionUsageContainer(props);
  if (state.type === "IDLE") {
    return null;
  }

  return (
    <UsageErrorBoundary
      fallback={(reset) => (
        <SubscriptionUsageSummary
          state={{ type: "UNAVAILABLE", reason: null, retryable: true }}
          onRefresh={async () => {
            reset();
            await onRefresh();
          }}
        />
      )}
      resetKey={`${props.integrationId}:${usageBoundaryResetKey(state)}`}
    >
      <SubscriptionUsageSummary state={state} onRefresh={onRefresh} />
    </UsageErrorBoundary>
  );
}
