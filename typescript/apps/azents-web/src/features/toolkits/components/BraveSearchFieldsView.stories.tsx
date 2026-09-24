import { rem } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { BraveSearchFieldsView } from "./BraveSearchFieldsView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const config = {
  country: "US",
  search_lang: "en",
  safesearch: "strict",
  timeout: 10,
};

const meta = {
  component: BraveSearchFieldsView,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(540)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    config,
    onConfigChange: fn(),
    credentials: null,
    onCredentialsChange: fn(),
    hasCredentials: false,
    replacingKey: false,
    onReplaceKey: fn(),
    onTestConnection: fn(),
    testState: { type: "IDLE" },
  },
} satisfies Meta<typeof BraveSearchFieldsView>;

export default meta;

type Story = StoryObj<typeof meta>;

export const NewKey = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Test connection" }),
    ).toBeDisabled();
    await userEvent.type(canvas.getByLabelText("Brave Search API key"), "k");
    await expect(args.onCredentialsChange).toHaveBeenLastCalledWith({
      api_key: "k",
    });
  },
} satisfies Story;

export const ExistingKey = {
  args: { hasCredentials: true },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByLabelText("Brave Search API key")).toBeNull();
    await userEvent.click(
      canvas.getByRole("button", { name: "Replace API key" }),
    );
    await expect(args.onReplaceKey).toHaveBeenCalledOnce();
    await userEvent.click(
      canvas.getByRole("button", { name: "Test connection" }),
    );
    await expect(args.onTestConnection).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const ReplacingKey = {
  args: { hasCredentials: true, replacingKey: true },
} satisfies Story;

export const Testing = {
  args: { hasCredentials: true, testState: { type: "TESTING" } },
} satisfies Story;

export const FailedTest = {
  args: {
    hasCredentials: true,
    testState: { type: "FAILURE", message: "Subscription token is invalid." },
  },
} satisfies Story;

export const SuccessfulTest = {
  args: {
    hasCredentials: true,
    testState: { type: "SUCCESS", message: "Connection succeeded." },
  },
} satisfies Story;
