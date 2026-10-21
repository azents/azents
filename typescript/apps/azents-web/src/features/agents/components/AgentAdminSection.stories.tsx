import { useTranslations } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import { AgentAdminSectionView } from "./AgentAdminSection";
import type { AgentAdminSectionViewProps } from "../containers/useAgentAdminSectionController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(
  props: Omit<AgentAdminSectionViewProps, "t">,
): React.ReactElement {
  const t = useTranslations("workspace.agents");
  return <AgentAdminSectionView {...props} t={t} />;
}
const admin = {
  id: "admin-1",
  agent_id: "agent-preview",
  workspace_user_id: "member-1",
  created_at: "2026-10-22T00:00:00Z",
};
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    readOnly: false,
    adminListState: { type: "READY", admins: [admin] },
    onRemoveAdmin: fn(),
    selectedMemberId: null,
    setSelectedMemberId: fn(),
    availableMembers: [{ value: "member-3", label: "Available member" }],
    getMemberName: (id: string): string => id,
    handleAddAdmin: fn(),
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const LastAdmin = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Remove" }),
    ).toBeDisabled();
  },
} satisfies Story;
export const Loading = {
  args: { adminListState: { type: "LOADING" } },
} satisfies Story;
export const Error = {
  args: { adminListState: { type: "ERROR" } },
} satisfies Story;
export const MultipleAdmins = {
  args: {
    adminListState: {
      type: "READY",
      admins: [
        admin,
        { ...admin, id: "admin-2", workspace_user_id: "member-2" },
      ],
    },
    selectedMemberId: "member-3",
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add Admin" }));
    await expect(args.handleAddAdmin).toHaveBeenCalled();
    const remove = canvas.getAllByRole("button", { name: "Remove" })[0];
    if (!remove) {
      throw new globalThis.Error("Expected an admin removal control");
    }
    await userEvent.click(remove);
    await expect(args.onRemoveAdmin).toHaveBeenCalledWith(admin);
  },
} satisfies Story;
export const ReadOnly = {
  args: { readOnly: true, selectedMemberId: "member-3" },
  play: async ({ canvasElement }) => {
    for (const button of within(canvasElement).getAllByRole("button")) {
      await expect(button).toBeDisabled();
    }
  },
} satisfies Story;
