"use client";
import { useState } from "react";
import { projectComposerSubscriptionIndicator } from "@/shared/subscription-usage/composerSubscriptionUsage";
import type { ComposerSubscriptionIndicatorState } from "../composerSubscriptionUsage";
import type { SubscriptionUsageState } from "@/shared/subscription-usage/subscriptionUsage";
interface ComposerSubscriptionUsagePopoverProps {
  compact: boolean;
  onRefresh: () => Promise<void> | void;
  state: SubscriptionUsageState;
}

export interface ComposerSubscriptionUsagePopoverViewProps {
  compact: ComposerSubscriptionUsagePopoverProps["compact"];
  onRefresh: ComposerSubscriptionUsagePopoverProps["onRefresh"];
  state: ComposerSubscriptionUsagePopoverProps["state"];
  opened: boolean;
  setOpened: React.Dispatch<React.SetStateAction<boolean>>;
  indicator: ComposerSubscriptionIndicatorState;
}
export function useComposerSubscriptionUsagePopoverController({
  compact,
  onRefresh,
  state,
}: ComposerSubscriptionUsagePopoverProps): ComposerSubscriptionUsagePopoverViewProps {
  const [opened, setOpened] = useState(false);
  const indicator = projectComposerSubscriptionIndicator(state);
  return { compact, onRefresh, state, opened, setOpened, indicator };
}
