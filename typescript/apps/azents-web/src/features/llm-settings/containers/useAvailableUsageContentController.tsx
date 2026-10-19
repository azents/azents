"use client";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  subscriptionUsageAdditionalLimits,
  subscriptionUsageSummaryLimits,
} from "@/shared/subscription-usage/subscriptionUsage";
import type {
  SubscriptionUsageAvailableResponse,
  SubscriptionUsageLimitResponse,
} from "@azents/public-client";

export interface AvailableUsageContentViewProps {
  snapshot: {
    snapshot: SubscriptionUsageAvailableResponse;
  }["snapshot"];
  t: ReturnType<
    typeof useTranslations<"workspace.llmSettings.subscriptionUsage">
  >;
  additionalOpened: boolean;
  setAdditionalOpened: React.Dispatch<React.SetStateAction<boolean>>;
  financialOpened: boolean;
  setFinancialOpened: React.Dispatch<React.SetStateAction<boolean>>;
  summaryLimits: SubscriptionUsageLimitResponse[];
  additionalLimits: SubscriptionUsageLimitResponse[];
}
export function useAvailableUsageContentController({
  snapshot,
}: {
  snapshot: SubscriptionUsageAvailableResponse;
}): AvailableUsageContentViewProps {
  const t = useTranslations("workspace.llmSettings.subscriptionUsage");
  const [additionalOpened, setAdditionalOpened] = useState(false);
  const [financialOpened, setFinancialOpened] = useState(false);
  const summaryLimits = subscriptionUsageSummaryLimits(snapshot);
  const additionalLimits = subscriptionUsageAdditionalLimits(snapshot);
  return {
    snapshot,
    t,
    additionalOpened,
    setAdditionalOpened,
    financialOpened,
    setFinancialOpened,
    summaryLimits,
    additionalLimits,
  };
}
