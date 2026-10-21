import { useRef } from "react";
import { expect, fn, within } from "storybook/test";
import { sectionAgent } from "./agent-section.story-fixtures";
import { AgentAvatarSectionView } from "./AgentAvatarSection";
import type { AgentAvatarSectionViewProps } from "../containers/useAgentAvatarSectionController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(
  props: Omit<AgentAvatarSectionViewProps, "inputRef">,
): React.ReactElement {
  const inputRef = useRef<HTMLInputElement>(null);
  return <AgentAvatarSectionView {...props} inputRef={inputRef} />;
}
const avatar = {
  filename: "preview.png",
  default: {
    url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96'%3E%3Ccircle cx='48' cy='48' r='40' fill='teal'/%3E%3C/svg%3E",
    width: 96,
    height: 96,
  },
  thumbnails: {},
  uploaded_at: "2026-10-22T00:00:00Z",
};
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    agent: sectionAgent,
    state: { type: "idle" },
    removeAvatar: fn(async (): Promise<void> => {}),
    handlePickFile: fn(),
    handleFileChange: fn(),
    busy: false,
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const NoImage = {} satisfies Story;
export const ExistingImage = {
  args: { agent: { ...sectionAgent, avatar } },
} satisfies Story;
export const Busy = {
  args: { state: { type: "uploading" }, busy: true },
} satisfies Story;
export const Error = {
  args: {
    state: { type: "error", message: "Only square images are supported." },
  },
} satisfies Story;
export const Deleting = {
  args: { agent: { ...sectionAgent, deletion_status: "deleting" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Upload image" }),
    ).toBeDisabled();
    await expect(
      canvasElement.querySelector('input[type="file"]'),
    ).toBeDisabled();
  },
} satisfies Story;
