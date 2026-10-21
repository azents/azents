import { expect, fn, userEvent, within } from "storybook/test";
import { WorkspaceJoinContent } from "./WorkspaceJoinView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: WorkspaceJoinContent,
  tags: ["ci-contract"],
  args: {
    handle: "acme",
    state: { type: "IDLE" },
    message: "Please add me",
    setMessage: fn(),
    submitMessage: fn(),
    onSubmitRequest: fn(),
    onAcceptInvitation: fn(),
    onDeclineInvitation: fn(),
  },
} satisfies Meta<typeof WorkspaceJoinContent>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Request = {
  play: async ({ args, canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button"));
    await expect(args.submitMessage).toHaveBeenCalledOnce();
  },
} satisfies Story;
export const Invitation = {
  args: { state: { type: "PENDING_INVITATION", invitationId: "invitation-1" } },
} satisfies Story;
export const Pending = {
  args: { state: { type: "PENDING_REQUEST" } },
} satisfies Story;
export const Submitted = {
  args: { state: { type: "SUBMITTED" } },
} satisfies Story;
export const Submitting = {
  args: { state: { type: "SUBMITTING" } },
} satisfies Story;
export const Loading = { args: { state: { type: "LOADING" } } } satisfies Story;
export const Error = {
  args: { state: { type: "ERROR", message: "Request failed" } },
} satisfies Story;
