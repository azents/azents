import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SubscriptionUsageSummary } from "./SubscriptionUsageSummary";
import type { SubscriptionUsageState } from "../subscriptionUsage";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const chatgptAvailable: SubscriptionUsageState = {
  type: "AVAILABLE",
  refreshing: false,
  snapshot: {
    type: "available",
    integration_id: "chatgpt-integration",
    provider: "chatgpt_oauth",
    fetched_at: "2026-07-19T09:30:00Z",
    plan_label: "Pro",
    limits: [
      {
        id: "primary",
        label: "5-hour limit",
        used_percent: 42,
        window_minutes: 300,
        resets_at: "2026-07-19T12:00:00Z",
        primary: true,
      },
      {
        id: "secondary",
        label: "Weekly limit",
        used_percent: 81,
        window_minutes: 10_080,
        resets_at: "2026-07-24T00:00:00Z",
        primary: true,
      },
      {
        id: "reviews",
        label: "Code review limit",
        used_percent: 18,
        window_minutes: null,
        resets_at: null,
        primary: false,
      },
    ],
    financial_details: {
      type: "chatgpt",
      has_credits: true,
      unlimited: false,
      balance: "120 credits",
      spend_limit: "500 credits",
      spend_used: "180 credits",
      spend_remaining_percent: 64,
      spend_resets_at: "2026-08-01T00:00:00Z",
      reached_type: null,
    },
  },
};

const xaiAvailable: SubscriptionUsageState = {
  type: "AVAILABLE",
  refreshing: false,
  snapshot: {
    type: "available",
    integration_id: "xai-integration",
    provider: "xai_oauth",
    fetched_at: "2026-07-19T09:30:00Z",
    plan_label: "SuperGrok",
    limits: [
      {
        id: "subscription",
        label: "Weekly limit",
        used_percent: 96,
        window_minutes: 10_080,
        resets_at: "2026-07-21T00:00:00Z",
        primary: true,
      },
    ],
    financial_details: {
      type: "xai",
      prepaid_balance_cents: 2540,
      payg_cap_cents: 10000,
      payg_used_cents: 1275,
      auto_top_up_enabled: true,
      auto_top_up_amount_cents: 2000,
      auto_top_up_monthly_maximum_cents: 10000,
    },
  },
};

const openRouterAvailable: SubscriptionUsageState = {
  type: "AVAILABLE",
  refreshing: false,
  snapshot: {
    type: "available",
    integration_id: "openrouter-integration",
    provider: "openrouter",
    fetched_at: "2026-07-19T09:30:00Z",
    plan_label: null,
    limits: [
      {
        id: "api-key-credit",
        label: "Monthly credit limit",
        used_percent: 27.5,
        window_minutes: null,
        resets_at: null,
        primary: true,
      },
    ],
    financial_details: {
      type: "openrouter",
      credit_limit: 100,
      credit_remaining: 72.5,
      usage: 40,
      usage_daily: 1,
      usage_weekly: 7.5,
      usage_monthly: 27.5,
      limit_reset: "monthly",
      include_byok_in_limit: false,
    },
  },
};

const meta = {
  component: SubscriptionUsageSummary,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(720)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    state: chatgptAvailable,
    onRefresh: fn(),
  },
} satisfies Meta<typeof SubscriptionUsageSummary>;

export default meta;

type Story = StoryObj<typeof meta>;

export const ChatGptTwoWindows = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("5-hour limit")).toBeVisible();
    await expect(canvas.getByText("Weekly limit")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Financial details" }),
    );
    await expect(canvas.getByText("120 credits")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Refresh subscription usage" }),
    );
    await expect(args.onRefresh).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const ReadOnlyProjection = {
  args: {
    state: {
      ...chatgptAvailable,
      snapshot: {
        ...chatgptAvailable.snapshot,
        financial_details: null,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Financial details" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const XaiFinancialDetails = {
  args: { state: xaiAvailable },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("96%")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Financial details" }),
    );
    await expect(canvas.getByText("$25.40")).toBeVisible();
    await expect(canvas.getByText("Auto top-up")).toBeVisible();
  },
} satisfies Story;

export const OpenRouterCreditLimit = {
  args: { state: openRouterAvailable },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("27.5%")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Financial details" }),
    );
    await expect(canvas.getByText("$72.50")).toBeVisible();
    await expect(canvas.getByText("Monthly usage")).toBeVisible();
  },
} satisfies Story;

export const OpenRouterUnlimitedHidden = {
  args: { state: { type: "IDLE" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("region", { name: "Subscription usage" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const AdditionalLimitDisclosure = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Additional limits (1)" }),
    );
    await expect(canvas.getByText("Code review limit")).toBeVisible();
  },
} satisfies Story;

export const ExternalXaiUsage = {
  args: {
    state: {
      type: "EXTERNAL",
      refreshing: false,
      snapshot: {
        type: "external",
        integration_id: "xai-integration",
        provider: "xai_oauth",
        fetched_at: "2026-07-19T09:30:00Z",
        url: "https://grok.com/usage",
        message: "Usage is managed on xAI.",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = canvas.getByRole("link", { name: /View usage on xAI/ });
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  },
} satisfies Story;

export const ReconnectRequired = {
  args: {
    state: {
      type: "UNAVAILABLE",
      reason: "reconnect_required",
      retryable: false,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(/Reconnect the provider account/),
    ).toBeVisible();
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
} satisfies Story;

export const TemporarilyUnavailable = {
  args: {
    state: {
      type: "UNAVAILABLE",
      reason: "temporarily_unavailable",
      retryable: true,
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Try again" }));
    await expect(args.onRefresh).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const StaleAfterRefreshFailure = {
  args: {
    state: {
      type: "STALE_ERROR",
      snapshot: chatgptAvailable.snapshot,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Update failed")).toBeVisible();
    await expect(canvas.getByText("5-hour limit")).toBeVisible();
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Disabled = {
  args: { state: { type: "DISABLED" } },
} satisfies Story;

export const Narrow = {
  args: { state: chatgptAvailable },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(320)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Story;
