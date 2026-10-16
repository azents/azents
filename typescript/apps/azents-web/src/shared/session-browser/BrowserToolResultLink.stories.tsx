import { expect, within } from "storybook/test";
import { BrowserToolResultLink } from "./BrowserToolResultLink";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: BrowserToolResultLink,
  parameters: {
    nextjs: {
      navigation: {
        pathname: "/w/team/agents/agent/sessions/session",
        query: { other: "retained" },
      },
    },
  },
  args: {
    name: "browser_open",
    result: JSON.stringify({
      page: { task_id: "task", id: "page", resource_incarnation: "generation" },
    }),
  },
} satisfies Meta<typeof BrowserToolResultLink>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ExactCurrentSession = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = canvas.getByRole("link", { name: "Open in Browser" });
    await expect(link).toHaveAttribute(
      "href",
      "/w/team/agents/agent/sessions/session?other=retained&page=browser&browserTaskId=task&browserPageId=page&browserIncarnation=generation",
    );
  },
} satisfies Story;
export const ClosedPageResult = {
  args: { result: '{"page":null}' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("link")).toBeNull();
  },
} satisfies Story;
