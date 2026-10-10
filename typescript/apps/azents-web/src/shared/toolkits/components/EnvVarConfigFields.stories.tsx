import { expect, fn, userEvent, within } from "storybook/test";
import { EnvVarConfigFieldsContainer } from "../EnvVarConfigFieldsContainer";
import { EnvVarConfigFields } from "./EnvVarConfigFields";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  title: "Toolkits/Provider fields/EnvVar",
  component: EnvVarConfigFields,
  args: {
    config: { entries: [] },
    credentials: null,
    hasCredentials: false,
    onConfigChange: fn(),
    onCredentialsChange: fn(),
    acknowledged: false,
    onAcknowledgedChange: fn(),
  },
} satisfies Meta<typeof EnvVarConfigFields>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty: Story = {};
export const Acknowledgement: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("checkbox"));
    await expect(args.onAcknowledgedChange).toHaveBeenCalledWith(true);
  },
};
export const ContainerAcknowledgement: Story = {
  render: (args) => <EnvVarConfigFieldsContainer {...args} />,
  play: async ({ canvasElement }) => {
    const checkbox = within(canvasElement).getByRole("checkbox");
    await expect(checkbox).not.toBeChecked();
    await userEvent.click(checkbox);
    await expect(checkbox).toBeChecked();
  },
};
export const Editing: Story = {
  args: {
    config: { entries: [{ name: "FIXTURE_KEY", masked: true }] },
    credentials: { values: { FIXTURE_KEY: "old" } },
  },
  play: async ({ canvasElement, args }) => {
    const inputs = within(canvasElement).getAllByRole("textbox");
    const input = inputs.find(
      (node) =>
        node instanceof HTMLInputElement && node.value === "FIXTURE_KEY",
    );
    if (!input) {
      throw new Error("Expected named environment input.");
    }
    await userEvent.type(input, "_X");
    await expect(args.onConfigChange).toHaveBeenCalled();
    await expect(args.onCredentialsChange).toHaveBeenCalled();
  },
};
