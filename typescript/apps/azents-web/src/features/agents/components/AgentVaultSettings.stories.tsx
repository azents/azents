import { expect, within } from "storybook/test";
import messages from "@/i18n/en-US-messages";
import { AgentVaultSettings } from "./AgentVaultSettings";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Agents/Vault/Settings",
  component: AgentVaultSettings,
  args: {
    state: {
      type: "ready",
      entries: [
        { name: "portal-password", contributor_label: "Workspace Owner" },
      ],
    },
    editor: null,
    pending: false,
    error: false,
    onEditor: (): void => {},
    onSubmit: (): Promise<void> => Promise.resolve(),
    t: (key): string => messages.workspace.agents.vault[key],
  },
} satisfies Meta<typeof AgentVaultSettings>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Registered = {} satisfies Story;

export const Empty = {
  args: { state: { type: "ready", entries: [] } },
} satisfies Story;

export const Unavailable = {
  args: { state: { type: "error" } },
} satisfies Story;

export const Replace = {
  args: { editor: { type: "replace", name: "portal-password" } },
  play: async ({ canvasElement }): Promise<void> => {
    const screen = within(canvasElement.ownerDocument.body);
    const dialog = await screen.findByRole("dialog", { name: "Replace value" });
    await expect(within(dialog).getByLabelText("Value")).toHaveValue("");
  },
} satisfies Story;
