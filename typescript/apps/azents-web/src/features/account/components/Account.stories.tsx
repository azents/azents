import { Account } from "./Account";
import type { AccountState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: Account,
} satisfies Meta<typeof Account>;

export default meta;

type Story = StoryObj<typeof meta>;

const loadedState: AccountState = {
  type: "LOADED",
  email: "alex@example.com",
  locale: "en-US",
  createdAt: new Date("2026-04-01T12:00:00.000Z"),
};

export const Loaded = {
  args: {
    state: loadedState,
    onSubmit: () => {},
  },
} satisfies Story;

export const Loading = {
  args: {
    state: { type: "LOADING" },
    onSubmit: () => {},
  },
} satisfies Story;

export const Error = {
  args: {
    state: { type: "ERROR", message: "Failed to load account information" },
    onSubmit: () => {},
  },
} satisfies Story;
