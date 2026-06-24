"use client";

/**
 * Workspace shell component.
 *
 * Desktop: fixed left sidebar + right content area.
 * Mobile: toggle Drawer sidebar with AppBar Burger.
 */
import { Box, Drawer, Group } from "@mantine/core";
import { useSidebar } from "@/shared/providers/sidebar";
import { WorkspaceSidebar } from "./WorkspaceSidebar";
import type { ReactNode } from "react";

interface WorkspaceShellProps {
  handle: string;
  children: ReactNode;
}

/** Sidebar width (px) */
const SIDEBAR_WIDTH = 250;

export function WorkspaceShell({
  handle,
  children,
}: WorkspaceShellProps): React.ReactElement {
  const { opened, close } = useSidebar();

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
        <WorkspaceSidebar handle={handle} onNavigate={close} />
      </Drawer>

      {/* Main layout — ensure full height */}
      <Group
        align="stretch"
        gap={0}
        wrap="nowrap"
        style={{
          flex: 1,
          minHeight: "calc(100dvh - var(--app-shell-header-offset, 0px))",
        }}
      >
        {/* Desktop sidebar */}
        <Box
          visibleFrom="sm"
          style={{
            width: SIDEBAR_WIDTH,
            minWidth: SIDEBAR_WIDTH,
            borderRight: "1px solid var(--mantine-color-default-border)",
          }}
          py="sm"
        >
          <WorkspaceSidebar handle={handle} />
        </Box>

        {/* Content area */}
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    </>
  );
}
