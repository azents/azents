import { expect, fn, userEvent, within } from "storybook/test";
import { GitHubUserCreation } from "./GitHubUserCreation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/GitHub user creation",
  component: GitHubUserCreation,
  args: { onCancel: fn(), onConfirm: fn() },
} satisfies Meta<typeof GitHubUserCreation>;
export default meta;
type Story = StoryObj<typeof meta>;
export const SharedReview: Story = {
  args: {
    state: {
      type: "REVIEW",
      candidate: {
        attempt_id: "attempt",
        account_id: 42,
        account_login: "fixture-user",
        account_avatar_url: null,
        app_id: "123",
        source: "platform_user",
        sharing_scope: "workspace_shared",
      },
    },
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("fixture-user")).toBeVisible();
    await expect(args.onConfirm).not.toHaveBeenCalled();
    await userEvent.click(canvas.getByRole("button", { name: /confirm/i }));
    await expect(args.onConfirm).toHaveBeenCalledOnce();
  },
};
export const AgentReview: Story = {
  args: {
    state: {
      type: "REVIEW",
      candidate: {
        attempt_id: "attempt",
        account_id: 42,
        account_login: "fixture-user",
        account_avatar_url: null,
        app_id: "123",
        source: "byoa_user",
        sharing_scope: "agent_only",
      },
    },
  },
};
export const Confirming: Story = {
  args: {
    state: {
      type: "CONFIRMING",
      candidate: {
        attempt_id: "attempt",
        account_id: 42,
        account_login: "fixture-user",
        account_avatar_url: null,
        app_id: "123",
        source: "platform_user",
        sharing_scope: "workspace_shared",
      },
    },
  },
};
export const LoadingReview: Story = {
  args: { state: { type: "REVIEW_LOADING", attemptId: "attempt" } },
};
export const Failed: Story = {
  args: { state: { type: "ERROR", reason: "stale", attemptId: "attempt" } },
};
export const Cancelling: Story = {
  args: { state: { type: "CANCELLING", attemptId: "attempt" } },
};
