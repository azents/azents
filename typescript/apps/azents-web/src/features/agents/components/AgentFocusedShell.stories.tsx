import { fn } from "storybook/test";
import { sectionAgent } from "./agent-section.story-fixtures";
import { AgentFocusedShellView } from "./AgentFocusedShell";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  tags: ["ci-contract"],
  component: AgentFocusedShellView,
  args: {
    children: <main>Session content</main>,
    drawerOpened: false,
    closeDrawer: fn(),
    mobileNavContext: { openAgentNavigation: fn() },
    sidebarProps: {
      handle: "preview",
      agent: sectionAgent,
      currentUser: null,
      adminAccessUrl: null,
      loggingOut: false,
      onLogout: fn(),
      sessionListScope: "team",
      onSessionListScopeChange: fn(),
      sessions: [],
      pinnedSessions: [],
      recentSessions: [],
      sessionsLoading: false,
      sessionsError: null,
      activeSessionId: null,
      creatingSession: false,
      renamingSessionId: null,
      archivingSessionId: null,
      pinningSessionId: null,
      onCreateSession: fn(),
      onRenameSession: fn(async (): Promise<void> => {}),
      onArchiveSession: fn(),
      onSetSessionPinned: fn(),
    },
  },
} satisfies Meta<typeof AgentFocusedShellView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Desktop = {} satisfies Story;
export const MobileClosed = {
  globals: { viewport: { value: "mobile1", isRotated: false } },
} satisfies Story;
export const MobileOpen = {
  args: { drawerOpened: true },
  globals: { viewport: { value: "mobile1", isRotated: false } },
} satisfies Story;
