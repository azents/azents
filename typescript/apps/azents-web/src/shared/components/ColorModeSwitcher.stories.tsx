import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ColorModeSwitcherView } from "./ColorModeSwitcher";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ColorModeSwitcherView,
  tags: ["ci-contract"],
  args: { mode: "light", preference: "system", handleSelect: fn() },
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ColorModeSwitcherView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const CurrentPreference = {} satisfies Story;
export const Dark = {
  args: { mode: "dark", preference: "dark" },
} satisfies Story;
export const LightSelection = {
  play: async ({ args, canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button"));
    await userEvent.click(
      await within(canvasElement.ownerDocument.body).findByRole("menuitem", {
        name: "Light",
      }),
    );
    await expect(args.handleSelect).toHaveBeenLastCalledWith("light");
  },
} satisfies Story;
