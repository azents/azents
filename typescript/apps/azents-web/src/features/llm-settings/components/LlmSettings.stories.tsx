import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { LlmSettings } from "./LlmSettings";
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
    id: "integration-xai-oauth",
    provider: "xai_oauth",
    name: "Personal Grok account",
    config: null,
    enabled: true,
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  },
];

const meta = {
  component: LlmSettings,
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
      workspaceModelSettings: null,
    },
    formModal: { type: "CLOSED" },
    mutationState: { type: "IDLE", error: null },
    canManage: true,
    providerOptions: [],
    availableProviderValues: ["xai", "xai_oauth"],
    modelOptions: [],
    catalogStates: new Map(),
    modelsLoading: false,
    renderSubscriptionUsage: () => null,
    onOpenCreate: () => {},
    onOpenEdit: () => {},
    onCloseModal: () => {},
    onCreate: () => {},
    onUpdate: () => {},
    onDelete: () => {},
    onToggleEnabled: () => {},
    onSyncCatalog: () => Promise.resolve(),
    onUpdateWorkspaceModelSettings: () => {},
  },
} satisfies Meta<typeof LlmSettings>;

export default meta;

type Story = StoryObj<typeof meta>;

export const XaiCredentialModes = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("xAI API key")).toBeVisible();
    await expect(canvas.getByText("xAI Grok OAuth")).toBeVisible();
    await expect(canvas.getByText("Production xAI API")).toBeVisible();
    await expect(canvas.getByText("Personal Grok account")).toBeVisible();
  },
} satisfies Story;
