import { expect, fn, userEvent, within } from "storybook/test";
import { SetupGuideView } from "./SetupGuide";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: SetupGuideView,
  tags: ["ci-contract"],
  args: {
    credType: "api_key",
    provider: "openrouter",
    opened: false,
    toggle: fn(),
  },
} satisfies Meta<typeof SetupGuideView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Collapsed = {
  play: async ({ args, canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button"));
    await expect(args.toggle).toHaveBeenCalledOnce();
  },
} satisfies Story;
export const OpenRouter = { args: { opened: true } } satisfies Story;
export const Aws = {
  args: { opened: true, credType: "aws_credentials", provider: "bedrock" },
} satisfies Story;
export const Gcp = {
  args: {
    opened: true,
    credType: "gcp_service_account",
    provider: "vertex_ai",
  },
} satisfies Story;
