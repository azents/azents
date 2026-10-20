import { expect, fn, userEvent, within } from "storybook/test";
import { AccountSidebarView } from "./AccountSidebar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: AccountSidebarView,
  tags: ["ci-contract"],
  args: { pathname: "/account", onNavigate: fn() },
} satisfies Meta<typeof AccountSidebarView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const General = {} satisfies Story;
export const Security = {
  args: { pathname: "/account/security" },
} satisfies Story;
export const ExternalAccounts = {
  args: { pathname: "/account/external-accounts" },
} satisfies Story;
export const MobileNavigation = {
  play: async ({ args, canvasElement }) => {
    await userEvent.click(
      within(canvasElement).getByRole("link", { name: "Workspaces" }),
    );
    await expect(args.onNavigate).toHaveBeenCalledOnce();
  },
} satisfies Story;
