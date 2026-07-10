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
