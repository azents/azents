import {
  AppShell,
  Box,
  Button,
  ScrollArea,
  Stack,
  Text,
  Textarea,
} from "@mantine/core";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";
import { ScrollContainedViewport } from "./ScrollContainedViewport";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

function LifecycleFixture(): ReactElement {
  const [workspace, setWorkspace] = useState(true);
  return workspace ? (
    <ScrollContainedViewport>
      <Button onClick={() => setWorkspace(false)}>Leave workspace</Button>
    </ScrollContainedViewport>
  ) : (
    <Box>
      <Button onClick={() => setWorkspace(true)}>Enter workspace</Button>
    </Box>
  );
}

const meta = {
  component: ScrollContainedViewport,
  tags: ["ci-contract"],
  args: {
    children: (
      <Stack h="100%" mih={0} gap={0}>
        <Text p="md">Internally scrollable workspace</Text>
        <ScrollArea
          flex={1}
          mih={0}
          viewportProps={{ style: { touchAction: "pan-y pinch-zoom" } }}
        >
          {Array.from({ length: 30 }, (_, index) => (
            <Text key={index} p="md">
              Scrollable content {index + 1}
            </Text>
          ))}
        </ScrollArea>
        <Box p="md">
          <Textarea aria-label="Native input" placeholder="Native input" />
        </Box>
      </Stack>
    ),
  },
} satisfies Meta<typeof ScrollContainedViewport>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Workspace = {} satisfies Story;

export const AppShellHeightChain = {
  render: (props) => (
    <AppShell>
      <AppShell.Main>
        <ScrollContainedViewport {...props} />
      </AppShell.Main>
    </AppShell>
  ),
  play: async ({ canvasElement }) => {
    const frame = canvasElement.querySelector(
      "[data-scroll-contained-viewport]",
    );
    if (!(frame instanceof HTMLElement)) {
      throw new Error("Expected the contained AppShell workspace.");
    }
    await expect(frame.getBoundingClientRect().height).toBe(
      document.documentElement.clientHeight,
    );
    const main = frame.closest(".mantine-AppShell-main");
    if (!(main instanceof HTMLElement)) {
      throw new Error("Expected the AppShell main ancestor.");
    }
    await expect(getComputedStyle(main).minHeight).toBe("0px");
    await expect(main.getBoundingClientRect().height).toBe(
      document.documentElement.clientHeight,
    );
  },
} satisfies Story;

export const RouteLifecycle = {
  render: () => <LifecycleFixture />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(getComputedStyle(document.body).position).toBe("fixed");
    await userEvent.click(
      canvas.getByRole("button", { name: "Leave workspace" }),
    );
    await waitFor(() =>
      expect(getComputedStyle(document.body).position).toBe("static"),
    );
    await userEvent.click(
      canvas.getByRole("button", { name: "Enter workspace" }),
    );
    await waitFor(() =>
      expect(getComputedStyle(document.body).position).toBe("fixed"),
    );
  },
} satisfies Story;
