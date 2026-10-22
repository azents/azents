import { useTranslations } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import { AgentDangerSectionView } from "./AgentDangerSection";
import type { AgentDangerSectionViewProps } from "../containers/useAgentDangerSectionController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(
  props: Omit<AgentDangerSectionViewProps, "t" | "tDanger">,
): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const tDanger = useTranslations("workspace.agents.detail.danger");
  return <AgentDangerSectionView {...props} t={t} tDanger={tDanger} />;
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    readOnly: false,
    opened: false,
    open: fn(),
    close: fn(),
    deleteMutation: { isPending: false },
    handleDelete: fn(),
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Closed = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Delete" }),
    );
    await expect(args.open).toHaveBeenCalled();
  },
} satisfies Story;
export const Confirm = {
  args: { opened: true },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    await expect(args.close).toHaveBeenCalled();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Delete" }),
    );
    await expect(args.handleDelete).toHaveBeenCalled();
  },
} satisfies Story;
export const Pending = {
  args: { opened: true, deleteMutation: { isPending: true } },
} satisfies Story;
export const ReadOnly = {
  args: { readOnly: true },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Delete" }),
    ).toBeDisabled();
  },
} satisfies Story;
