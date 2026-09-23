import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { LlmIntegrations } from "./LlmIntegrations";
import type { LlmProviderIntegrationResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const integrations: LlmProviderIntegrationResponse[] = [
  {
    id: "integration-xai-api-key",
    provider: "xai",
    name: "Production xAI API",
    config: null,
    enabled: true,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
  {
    id: "integration-chatgpt-oauth",
    provider: "chatgpt_oauth",
    name: "Personal ChatGPT account",
    config: null,
    enabled: true,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
  {
    id: "integration-xai-oauth",
    provider: "xai_oauth",
    name: "Personal Grok account",
    config: null,
    enabled: true,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
  {
    id: "integration-kimi-oauth",
    provider: "kimi_oauth",
    name: "Kimi Code subscription",
    config: {
      type: "kimi_oauth",
      connection_method: "device",
      status: "refresh_required",
      connected_at: "2026-07-19T00:00:00Z",
      last_refreshed_at: "2026-07-19T00:00:00Z",
      last_failed_at: null,
      last_failure_reason: null,
    },
    enabled: true,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  },
  {
    id: "integration-openrouter",
    provider: "openrouter",
    name: "OpenRouter workspace",
    config: null,
    enabled: true,
    created_at: "2026-07-19T00:00:00Z",
    updated_at: "2026-07-19T00:00:00Z",
  },
];

const meta = {
  component: LlmIntegrations,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    listState: {
      type: "READY",
      integrations,
    },
    formModal: { type: "CLOSED" },
    mutationState: { type: "IDLE", error: null },
    canManage: true,
    availableProviderValues: ["xai", "xai_oauth", "kimi_oauth", "openrouter"],
    renderSubscriptionUsage: () => null,
    onOpenCreate: () => {},
    onOpenEdit: fn(),
    onCloseModal: () => {},
    onCreate: () => {},
    onUpdate: () => {},
    onDelete: () => {},
    onToggleEnabled: () => {},
  },
} satisfies Meta<typeof LlmIntegrations>;

export default meta;

type Story = StoryObj<typeof meta>;

export const LoadedOwner = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Production xAI API")).toBeVisible();
    await expect(canvas.getByText("Personal ChatGPT account")).toBeVisible();
    await expect(canvas.getByText("Personal Grok account")).toBeVisible();
    await expect(canvas.getByText("Kimi Code subscription")).toBeVisible();
    await expect(canvas.getByText("Reconnect required")).toBeVisible();
    await expect(canvas.getByText("OpenRouter workspace")).toBeVisible();
    for (const name of [
      "Personal ChatGPT account",
      "Personal Grok account",
      "Kimi Code subscription",
    ]) {
      await expect(
        canvas.getByRole("button", { name: `Reauthenticate ${name}` }),
      ).toBeVisible();
    }
    await expect(
      canvas.queryByRole("button", {
        name: "Reauthenticate Production xAI API",
      }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      canvas.getByRole("button", {
        name: "Reauthenticate Personal Grok account",
      }),
    );
    await expect(args.onOpenEdit).toHaveBeenCalledWith(integrations[2]);
  },
} satisfies Story;

export const LoadedReadOnly = {
  args: { canManage: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Personal ChatGPT account")).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: /Reauthenticate/ }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const EmptyOwner = {
  args: {
    listState: { type: "READY", integrations: [] },
  },
} satisfies Story;

export const Loading = {
  args: { listState: { type: "LOADING" } },
} satisfies Story;

export const Error = {
  args: { listState: { type: "ERROR" } },
} satisfies Story;
