import { Box, Text } from "@mantine/core";
import { fn } from "storybook/test";
import { WorkspaceSidebarView } from "./WorkspaceSidebar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Workspace/Sidebar",
  component: WorkspaceSidebarView,
  args: {
    handle: "sample",
    pathname: "/w/sample",
    renderAgentSection: () => <Text size="sm">Sample Agent</Text>,
  },
  decorators: [
    (Story) => (
      <Box w={250}>
        <Story />
      </Box>
    ),
  ],
} satisfies Meta<typeof WorkspaceSidebarView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Home: Story = {};
export const PersonalTools: Story = {
  args: { pathname: "/w/sample/personal-tools" },
};
export const MobileDrawer: Story = {
  args: { pathname: "/w/sample/members", onNavigate: fn() },
};
