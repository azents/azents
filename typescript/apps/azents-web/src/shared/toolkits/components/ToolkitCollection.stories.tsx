import { Badge, Button, Group, Switch } from "@mantine/core";
import { expect, fn, userEvent, within } from "storybook/test";
import { ToolkitCard, ToolkitCollection } from "./ToolkitCollection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Shared Collection",
  component: ToolkitCard,
  args: {
    name: "Research sources",
    toolkitType: "mcp",
    providerName: "Model Context Protocol",
    description: "Shared presentation for every Toolkit owner.",
    badges: <Badge variant="light">Ready</Badge>,
    actions: (
      <Button size="xs" variant="subtle">
        Details
      </Button>
    ),
  },
} satisfies Meta<typeof ToolkitCard>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Standard: Story = {};
export const OwnershipParity: Story = {
  render: (props) => (
    <ToolkitCollection>
      {["Workspace", "Agent", "Personal"].map((scope) => (
        <ToolkitCard
          {...props}
          key={scope}
          name={`${scope} connection`}
          badges={
            <Group gap="xs">
              <Badge variant="outline">{scope}</Badge>
              <Badge color="green">Ready</Badge>
            </Group>
          }
        />
      ))}
    </ToolkitCollection>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const scope of ["Workspace", "Agent", "Personal"]) {
      const card = canvas.getByRole("article", { name: `${scope} connection` });
      await expect(
        within(card).getByRole("button", { name: "Details" }),
      ).toBeVisible();
    }
  },
};
export const PersonalActions: Story = {
  args: {
    control: <Switch aria-label="Enable Research sources" defaultChecked />,
    actions: (
      <>
        <Button size="xs" variant="default" onClick={fn()}>
          Settings
        </Button>
        <Button size="xs" variant="default">
          Agent access
        </Button>
        <Button size="xs" variant="subtle">
          Test connection
        </Button>
      </>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const control = canvas.getByRole("switch", {
      name: "Enable Research sources",
    });
    await expect(control).toBeChecked();
    await userEvent.click(control);
    await expect(control).not.toBeChecked();
  },
};
export const MobileLongName: Story = {
  globals: { viewport: { value: "mobile1", isRotated: false } },
  args: {
    name: "A connection with a long organization and project name that must remain readable on mobile",
    description:
      "Long configuration descriptions wrap within the same standard card for every scope.",
  },
};
