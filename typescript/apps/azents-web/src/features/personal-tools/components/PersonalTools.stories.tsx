import { expect, fn, userEvent, within } from "storybook/test";
import { personalToolFixture } from "../personal-tools-fixtures";
import { PersonalTools } from "./PersonalTools";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Personal Tools/Connections",
  component: PersonalTools,
  args: {
    handle: "workspace",
    state: {
      type: "READY",
      items: [
        personalToolFixture(),
        personalToolFixture({
          id: "github",
          name: "Personal GitHub",
          toolkit_type: "github",
          access_mode: "selected",
          readiness: "authorization_required",
        }),
      ],
    },
    pending: false,
    error: false,
    deleteTarget: null,
    testResult: null,
    onReload: fn(),
    onDelete: fn(),
    onConfirmDelete: fn(),
    onToggle: fn(),
    onTest: fn(),
  },
} satisfies Meta<typeof PersonalTools>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Connections: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const testButton = canvas.getAllByRole("button", {
      name: "Test connection",
    })[0];
    if (!testButton) {
      throw new Error("Expected a saved connection test action");
    }
    await userEvent.click(testButton);
    await expect(args.onTest).toHaveBeenCalledWith(personalToolFixture());
    const edit = canvas.getAllByRole("link", { name: "Settings" })[0];
    await expect(edit).toHaveAttribute(
      "href",
      "/w/workspace/personal-tools/personal-example/edit",
    );
  },
};
export const Empty: Story = { args: { state: { type: "READY", items: [] } } };
export const Loading: Story = { args: { state: { type: "LOADING" } } };
export const LoadError: Story = { args: { state: { type: "ERROR" } } };
export const Saving: Story = { args: { pending: true } };
export const DeleteConfirmation: Story = {
  args: { deleteTarget: personalToolFixture() },
  play: async ({ args }) => {
    const dialog = within(document.body).getByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Delete" }),
    );
    await expect(args.onConfirmDelete).toHaveBeenCalled();
  },
};
export const FailedDelete: Story = {
  args: { deleteTarget: personalToolFixture(), error: true },
};
export const MobileLongNames: Story = {
  globals: { viewport: { value: "mobile1", isRotated: false } },
  parameters: { layout: "fullscreen" },
  args: {
    state: {
      type: "READY",
      items: [
        personalToolFixture({
          name: "Personal connection with a very long account and organization name that remains readable on small screens",
        }),
      ],
    },
  },
};
