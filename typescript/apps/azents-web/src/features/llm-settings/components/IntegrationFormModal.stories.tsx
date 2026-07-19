import { expect, fn, userEvent, within } from "storybook/test";
import { IntegrationFormModal } from "./IntegrationFormModal";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: IntegrationFormModal,
  args: {
    handle: "acme",
    availableProviderValues: ["xai", "xai_oauth"],
    formModal: {
      type: "EDIT",
      integration: {
        id: "integration-xai-api-key",
        provider: "xai",
        name: "Production xAI API",
        config: null,
        enabled: true,
        created_at: "2026-07-10T00:00:00Z",
        updated_at: "2026-07-10T00:00:00Z",
      },
    },
    mutationState: { type: "IDLE", error: null },
    onClose: fn(),
    onCreate: fn(),
    onUpdate: fn(),
  },
} satisfies Meta<typeof IntegrationFormModal>;

export default meta;

type Story = StoryObj<typeof meta>;

export const OpenRouterEditPreservesOmittedApiKey = {
  args: {
    availableProviderValues: ["openrouter"],
    formModal: {
      type: "EDIT",
      integration: {
        id: "integration-openrouter",
        provider: "openrouter",
        name: "OpenRouter workspace",
        config: null,
        enabled: true,
        created_at: "2026-07-19T00:00:00Z",
        updated_at: "2026-07-19T00:00:00Z",
      },
    },
  },
  play: async ({ args, canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByDisplayValue("OpenRouter workspace")).toBeVisible();
    await expect(
      page.getByPlaceholderText("Leave empty to keep current value"),
    ).toHaveValue("");

    await userEvent.click(page.getByRole("button", { name: "Save" }));

    await expect(args.onUpdate).toHaveBeenCalledWith({
      name: "OpenRouter workspace",
    });
  },
} satisfies Story;

export const XaiEditPreservesOmittedApiKey = {
  play: async ({ args, canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByDisplayValue("Production xAI API")).toBeVisible();
    await expect(
      page.getByPlaceholderText("Leave empty to keep current value"),
    ).toHaveValue("");

    await userEvent.click(page.getByRole("button", { name: "Save" }));

    await expect(args.onUpdate).toHaveBeenCalledWith({
      name: "Production xAI API",
    });
  },
} satisfies Story;

export const KimiReconnectRequired = {
  args: {
    availableProviderValues: ["kimi_oauth"],
    formModal: {
      type: "EDIT",
      integration: {
        id: "integration-kimi",
        provider: "kimi_oauth",
        name: "Team Kimi subscription",
        config: {
          type: "kimi_oauth",
          connection_method: "device",
          status: "refresh_required",
          connected_at: "2026-07-19T00:00:00Z",
          last_refreshed_at: "2026-07-19T00:00:00Z",
          last_failed_at: "2026-07-19T01:00:00Z",
          last_failure_reason: "refresh token rejected",
        },
        enabled: true,
        created_at: "2026-07-19T00:00:00Z",
        updated_at: "2026-07-19T01:00:00Z",
      },
    },
  },
  play: async ({ canvasElement }) => {
    const page = within(canvasElement.ownerDocument.body);
    await expect(page.getByText("Reconnect required")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Reconnect Kimi subscription" }),
    ).toBeVisible();
    await expect(page.queryByLabelText("API Key")).not.toBeInTheDocument();
  },
} satisfies Story;
