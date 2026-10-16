import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";
import { BrowserAvailabilityProvider } from "./BrowserAvailability";
import { BrowserToolResultLink } from "./BrowserToolResultLink";
import type { BrowserToolResultLinkProps } from "./useBrowserToolResultLink";
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
  decorators: [
    (Story) => (
      <BrowserAvailabilityProvider enabled>
        <Story />
      </BrowserAvailabilityProvider>
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = canvas.getByRole("link", { name: "Open in Browser" });
    await expect(link).toHaveAttribute(
      "href",
      "/w/team/agents/agent/sessions/session?other=retained&page=browser&browserTaskId=task&browserPageId=page&browserIncarnation=generation",
    );
  },
} satisfies Story;
export const DisabledAgent = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("link")).toBeNull();
  },
} satisfies Story;

function AvailabilityFixture(
  props: BrowserToolResultLinkProps,
): React.ReactElement {
  const [enabled, setEnabled] = useState(true);
  return (
    <BrowserAvailabilityProvider enabled={enabled}>
      <button onClick={() => setEnabled(false)}>Disable Browser</button>
      <BrowserToolResultLink {...props} />
    </BrowserAvailabilityProvider>
  );
}
export const DisableRemovesExistingLink = {
  render: (props) => <AvailabilityFixture {...props} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("link", { name: "Open in Browser" }),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Disable Browser" }),
    );
    await expect(canvas.queryByRole("link")).toBeNull();
  },
} satisfies Story;

export const ClosedPageResult = {
  decorators: ExactCurrentSession.decorators,
  args: { result: '{"page":null}' },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("link")).toBeNull();
  },
} satisfies Story;
