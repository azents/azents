import { Box, rem, Text } from "@mantine/core";
import { IconFolder } from "@tabler/icons-react";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
import { sessionPanelViews } from "./sessionPanel";
import { SessionSidePanel } from "./SessionSidePanel";
import type { SessionPanelView } from "./sessionPanel";
import type { SessionSidePanelProps } from "./SessionSidePanel";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

function InteractivePanel(props: SessionSidePanelProps): ReactElement {
  const [active, setActive] = useState<SessionPanelView>(props.activeId);
  return (
    <Box h="100dvh">
      <SessionSidePanel {...props} activeId={active} onSelect={setActive}>
        <Box p="md">
          <Text>{active}</Text>
        </Box>
      </SessionSidePanel>
    </Box>
  );
}

const meta = {
  component: SessionSidePanel,
  render: (props) => <InteractivePanel {...props} />,
  args: {
    items: sessionPanelViews.map((id) => ({
      id,
      label: id,
      icon: <IconFolder size="1rem" />,
    })),
    activeId: "files",
    onSelect: (): void => {},
    onClose: (): void => {},
    title: "Session panel",
    closeLabel: "Close session panel",
    previousTabsLabel: "Scroll to previous tabs",
    nextTabsLabel: "Scroll to more tabs",
    mobile: false,
    children: null,
  },
} satisfies Meta<typeof SessionSidePanel>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Desktop = {} satisfies Story;
export const Mobile = {
  args: { mobile: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const files = canvas.getByRole("tab", { name: "files" });
    await userEvent.click(files);
    await userEvent.keyboard("{End}");
    await expect(
      canvas.getByRole("tab", { name: "raw-events" }),
    ).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Home}");
    await expect(files).toHaveAttribute("aria-selected", "true");
  },
} satisfies Story;
export const LongLabels = {
  args: {
    mobile: true,
    items: sessionPanelViews.map((id) => ({
      id,
      label: `Session ${id} information`,
      icon: <IconFolder size="1rem" />,
    })),
  },
} satisfies Story;

export const ScrollableContent = {
  args: {
    mobile: true,
    children: (
      <Box data-testid="scroll-owner" style={{ overflowY: "auto" }} p="md">
        <Box h={rem(1600)}>
          <Text>Long session panel content</Text>
        </Box>
      </Box>
    ),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const scrollOwner = canvas.getByTestId("scroll-owner");
    await expect(scrollOwner.scrollHeight).toBeGreaterThan(
      scrollOwner.clientHeight,
    );
    scrollOwner.scrollTop = 160;
    await expect(scrollOwner.scrollTop).toBeGreaterThan(0);
  },
} satisfies Story;
