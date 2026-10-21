import { expect, fn, within } from "storybook/test";
import { WorkspaceMembersView } from "./WorkspaceMembersView";
import type { WorkspaceMembersContainerProps } from "../containers/useWorkspaceMembers";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const member = {
  id: "member-preview",
  workspace_id: "workspace-preview",
  user_id: "user-preview",
  name: "Preview Member",
  role: "member",
  created_at: "2026-10-22T00:00:00Z",
  updated_at: "2026-10-22T00:00:00Z",
};
const args: WorkspaceMembersContainerProps = {
  handle: "preview",
  currentWorkspaceUserId: "manager-preview",
  currentRole: "manager",
  inviteFormState: { type: "IDLE", error: null, success: null },
  membersState: { type: "READY", members: [] },
  invitationsState: { type: "READY", invitations: [] },
  joinRequestsState: { type: "READY", joinRequests: [] },
  notification: null,
  onInvite: fn(),
  onClearInviteStatus: fn(),
  onUpdateRole: fn(),
  onRemoveMember: fn(),
  onCancelInvitation: fn(),
  onApproveJoinRequest: fn(),
  onRejectJoinRequest: fn(),
  onMuteJoinRequest: fn(),
  onDeleteJoinRequest: fn(),
  onClearNotification: fn(),
};
const meta = {
  component: WorkspaceMembersView,
  tags: ["ci-contract"],
  args,
} satisfies Meta<typeof WorkspaceMembersView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {} satisfies Story;
export const Loading = {
  args: {
    membersState: { type: "LOADING" },
    invitationsState: { type: "LOADING" },
    joinRequestsState: { type: "LOADING" },
  },
} satisfies Story;
export const Error = {
  args: {
    membersState: { type: "ERROR" },
    invitationsState: { type: "ERROR" },
    joinRequestsState: { type: "ERROR" },
  },
} satisfies Story;
export const InviteSending = {
  args: { inviteFormState: { type: "SENDING" } },
  play: async ({ canvasElement }) => {
    for (const input of canvasElement.querySelectorAll("input")) {
      await expect(input).toBeDisabled();
    }
  },
} satisfies Story;
export const InviteError = {
  args: {
    inviteFormState: {
      type: "IDLE",
      error: "inviteAlreadyInvited",
      success: null,
    },
  },
} satisfies Story;
export const InviteSuccess = {
  args: {
    inviteFormState: { type: "IDLE", error: null, success: "inviteSuccess" },
  },
} satisfies Story;
export const ManageableMember = {
  args: { membersState: { type: "READY", members: [member] } },
} satisfies Story;
export const ProtectedOwnerAndSelf = {
  args: {
    membersState: {
      type: "READY",
      members: [
        { ...member, role: "owner" },
        { ...member, id: "manager-preview", name: "Current user" },
      ],
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("button", { name: /remove member/i }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
export const ReadOnly = {
  args: {
    currentRole: "member",
    membersState: { type: "READY", members: [member] },
  },
} satisfies Story;
export const PendingActions = {
  args: {
    invitationsState: {
      type: "READY",
      invitations: [
        {
          id: "invite-preview",
          workspace_id: "workspace-preview",
          email: "preview@example.invalid",
          role: "member",
          invited_by: "manager-preview",
          status: "pending",
          created_at: member.created_at,
          updated_at: member.updated_at,
        },
      ],
    },
    joinRequestsState: {
      type: "READY",
      joinRequests: [
        {
          id: "request-preview",
          workspace_id: "workspace-preview",
          user_id: "new-user",
          message: "Please add me to this workspace.",
          status: "pending",
          created_at: member.created_at,
        },
      ],
    },
  },
} satisfies Story;
