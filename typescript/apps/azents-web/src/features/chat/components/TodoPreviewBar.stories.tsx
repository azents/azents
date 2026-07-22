import { expect, userEvent, within } from "storybook/test";
import { TodoPreviewBar } from "./TodoPreviewBar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "chat/TodoPreviewBar",
  component: TodoPreviewBar,
  args: {
    isMobile: false,
    goal: null,
    onClearGoal: () => Promise.resolve(true),
    onUpdateGoal: () => Promise.resolve(true),
    onPauseGoal: () => Promise.resolve(true),
    onResumeGoal: () => Promise.resolve(true),
  },
} satisfies Meta<typeof TodoPreviewBar>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithProgress: Story = {
  args: {
    todo: {
      items: [
        {
          content:
            "Write the todo UI design document and keep the preview on a single line",
          status: "in_progress",
        },
        {
          content: "Review mobile sheet interactions",
          status: "pending",
        },
        {
          content: "Ship the first pass",
          status: "completed",
        },
      ],
    },
  },
};

export const Mobile: Story = {
  args: {
    isMobile: true,
    todo: {
      items: [
        {
          content:
            "Implement mobile bottom sheet rendering while preserving the original todo item order",
          status: "in_progress",
        },
        {
          content: "Avoid moving completed items to the bottom",
          status: "completed",
        },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /todo/i }));
    const page = within(canvasElement.ownerDocument.body);
    const sheet = await page.findByRole("dialog");
    await expect(sheet).toBeVisible();
    await expect(sheet.getBoundingClientRect().height).toBeLessThanOrEqual(
      Math.min(window.innerHeight * 0.8, 720) + 1,
    );
  },
};

export const GoalAndTodo: Story = {
  args: {
    goal: {
      objective: "Goal continuation/backend implementation",
      status: "active",
    },
    todo: {
      items: [{ content: "Run backend checks", status: "pending" }],
    },
  },
};

export const LongGoal: Story = {
  args: {
    goal: {
      objective:
        "Remove per-user OAuth handling and consolidate generic MCP, Notion, and Sentry toolkits under ToolkitConfig-level OAuth behavior",
      status: "active",
    },
    todo: { items: [] },
  },
};

export const MarkdownGoal: Story = {
  args: {
    goal: {
      objective: `# Ship the **Goal** experience

- [ ] Render the full objective as Markdown
- [ ] Keep the [preview](https://example.com) as plain text`,
      status: "active",
    },
    todo: { items: [] },
  },
};

export const PausedGoal: Story = {
  args: {
    goal: {
      objective: "Review before continuing automatic goal work",
      status: "paused",
    },
    todo: { items: [] },
  },
};

export const BlockedGoal: Story = {
  args: {
    goal: {
      objective: "Verify production deployment after credentials are restored",
      status: "blocked",
    },
    todo: { items: [] },
  },
};

export const Empty: Story = {
  args: {
    todo: { items: [] },
  },
};
