"use client";

/**
 * Workspace shell component.
 *
 * Desktop: fixed left sidebar + right content area.
 * Mobile: toggle Drawer sidebar with AppBar Burger.
 */
import { Box, Drawer, Group, rem } from "@mantine/core";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceShell } from "../containers/useWorkspaceShell";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import type { WorkspaceShellViewProps } from "../containers/useWorkspaceShell";

/** Sidebar width. */
const SIDEBAR_WIDTH = rem(250);

export const WorkspaceShell = createReactContainer(
  "WorkspaceShell",
  useWorkspaceShell,
  WorkspaceShellView,
);

export function WorkspaceShellView({
  handle,
  children,
  renderAgentSection,
  opened,
  close,
}: WorkspaceShellViewProps): React.ReactElement {
  return (
    <>
      {/* Mobile Drawer */}
      <Drawer
        opened={opened}
        onClose={close}
        size={SIDEBAR_WIDTH}
        hiddenFrom="sm"
        withCloseButton={false}
        padding="sm"
      >
        <WorkspaceSidebar
          handle={handle}
          onNavigate={close}
          renderAgentSection={renderAgentSection}
        />
      </Drawer>

      {/* Main layout — ensure full height */}
      <Group
        align="stretch"
        gap={0}
        wrap="nowrap"
        style={{
          flex: 1,
          minHeight: "calc(100dvh - var(--app-shell-header-offset, 0rem))",
        }}
      >
        {/* Desktop sidebar */}
        <Box
          visibleFrom="sm"
          style={{
            width: SIDEBAR_WIDTH,
            minWidth: SIDEBAR_WIDTH,
            borderRight: `${rem(1)} solid var(--mantine-color-default-border)`,
          }}
          py="sm"
        >
          <WorkspaceSidebar
            handle={handle}
            renderAgentSection={renderAgentSection}
          />
        </Box>

        {/* Content area */}
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    </>
  );
}
