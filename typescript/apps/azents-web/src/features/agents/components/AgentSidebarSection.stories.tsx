import { useTranslations } from "next-intl";
import { fn } from "storybook/test";
import { sectionAgent } from "./agent-section.story-fixtures";
import { AgentSidebarSectionView } from "./AgentSidebarSection";
import type { AgentSidebarSectionViewProps } from "../containers/useAgentSidebarSectionController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture(
  props: Omit<AgentSidebarSectionViewProps, "t">,
): React.ReactElement {
  const t = useTranslations("workspace.sidebar");
  return <AgentSidebarSectionView {...props} t={t} />;
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    onNavigate: fn(),
    workspaceBase: "/w/preview",
    agentsBase: "/w/preview/agents",
    state: { type: "READY", visible: [], totalCount: 0 },
    activeAgentId: null,
    query: "",
    setQuery: fn(),
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {} satisfies Story;
export const Loading = { args: { state: { type: "LOADING" } } } satisfies Story;
export const NoMatches = { args: { query: "missing" } } satisfies Story;
export const Populated = {
  args: {
    state: { type: "READY", visible: [sectionAgent], totalCount: 1 },
    activeAgentId: sectionAgent.id,
  },
} satisfies Story;
export const Overflow = {
  args: { state: { type: "READY", visible: [sectionAgent], totalCount: 12 } },
} satisfies Story;
