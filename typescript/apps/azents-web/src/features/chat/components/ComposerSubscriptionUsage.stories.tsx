import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ComposerSubscriptionUsagePopover } from "./ComposerSubscriptionUsage";
import type { SubscriptionUsageState } from "@/features/llm-settings/subscriptionUsage";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const availableSnapshot = {
  type: "available" as const,
  integration_id: "integration-chatgpt",
  provider: "chatgpt_oauth" as const,
  fetched_at: "2026-07-19T12:00:00Z",
  plan_label: "Plus",
  limits: [
    {
      id: "primary",
      label: "5 hour limit",
      used_percent: 73,
      window_minutes: 300,
      resets_at: "2026-07-19T14:00:00Z",
      primary: true,
    },
    {
      id: "secondary",
      label: "Weekly limit",
      used_percent: 41,
      window_minutes: 10_080,
      resets_at: "2026-07-22T12:00:00Z",
      primary: true,
    },
  ],
  financial_details: {
    type: "chatgpt" as const,
    has_credits: true,
    unlimited: false,
    balance: "must-not-render",
    spend_limit: "must-not-render",
    spend_used: null,
    spend_remaining_percent: null,
    spend_resets_at: null,
    reached_type: null,
  },
};

function Preview({
  compact,
  onRefresh,
  state,
}: {
  compact: boolean;
  onRefresh: () => Promise<void> | void;
  state: SubscriptionUsageState;
}): React.ReactElement {
  return (
    <StorybookCanvas maxWidth={rem(360)}>
      <ComposerSubscriptionUsagePopover
        compact={compact}
        state={state}
        onRefresh={onRefresh}
      />
    </StorybookCanvas>
  );
}

const meta = {
  component: Preview,
  args: {
    compact: false,
    onRefresh: fn(),
  },
} satisfies Meta<typeof Preview>;

export default meta;
type Story = StoryObj<typeof meta>;

export const AvailableNormal = {
  args: {
    state: {
      type: "AVAILABLE",
      snapshot: {
        ...availableSnapshot,
        limits: [
          {
            id: "primary",
            label: "5 hour limit",
            used_percent: 42,
            window_minutes: 300,
            resets_at: "2026-07-19T14:00:00Z",
            primary: true,
          },
        ],
      },
      refreshing: false,
    },
  },
} satisfies Story;

export const AvailableWarning = {
  args: {
    state: {
      type: "AVAILABLE",
      snapshot: availableSnapshot,
      refreshing: false,
    },
  },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      page.getByRole("button", { name: /Subscription usage:.*73%/ }),
    );
    await expect(page.getByText("73%")).toBeVisible();
    await expect(page.getByText("5 hour limit")).toBeVisible();
    await expect(page.queryByText("must-not-render")).not.toBeInTheDocument();
    await userEvent.click(
      page.getByRole("button", { name: "Refresh subscription usage" }),
    );
    await expect(args.onRefresh).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const CompactMobile = {
  args: {
    compact: true,
    state: {
      type: "AVAILABLE",
      snapshot: availableSnapshot,
      refreshing: false,
    },
  },
} satisfies Story;

export const Critical = {
  args: {
    state: {
      type: "AVAILABLE",
      snapshot: {
        ...availableSnapshot,
        limits: [
          {
            id: "primary",
            label: "5 hour limit",
            used_percent: 96,
            window_minutes: 300,
            resets_at: "2026-07-19T14:00:00Z",
            primary: true,
          },
        ],
      },
      refreshing: false,
    },
  },
} satisfies Story;

export const Loading = {
  args: { state: { type: "LOADING" } },
} satisfies Story;

export const Stale = {
  args: {
    state: { type: "STALE_ERROR", snapshot: availableSnapshot },
  },
} satisfies Story;

export const External = {
  args: {
    state: {
      type: "EXTERNAL",
      refreshing: false,
      snapshot: {
        type: "external",
        integration_id: "integration-xai",
        provider: "xai_oauth",
        fetched_at: "2026-07-19T12:00:00Z",
        url: "https://grok.com/usage",
        message: "Usage is managed on xAI.",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      page.getByRole("button", { name: /Subscription usage:/ }),
    );
    const link = page.getByRole("link", { name: /View usage on xAI/ });
    await expect(link).toHaveAttribute("target", "_blank");
    await expect(link).toHaveAttribute("rel", "noopener noreferrer");
  },
} satisfies Story;

export const Unavailable = {
  args: {
    state: {
      type: "UNAVAILABLE",
      reason: "temporarily_unavailable",
      retryable: true,
    },
  },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      page.getByRole("button", { name: /Subscription usage: Unavailable/ }),
    );
    await userEvent.click(page.getByRole("button", { name: "Try again" }));
    await expect(args.onRefresh).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Unsupported = {
  args: { state: { type: "DISABLED" } },
} satisfies Story;
