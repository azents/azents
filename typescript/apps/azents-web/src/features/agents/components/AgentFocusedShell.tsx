"use client";
import { Box, Drawer, Group, rem } from "@mantine/core";
/**
 * Agent-focused route shell.
 *
 * Removes the workspace-wide sidebar from Agent detail screens and gives Agent
 * work a dedicated left rail plus mobile drawer entry point.
 */
import { AgentFocusedShellMobileNavProvider } from "@/shared/agent-session/AgentFocusedShellMobileNav";

import { useAgentFocusedShellController } from "../containers/useAgentFocusedShellController";
import { AgentFocusedSidebar } from "./AgentFocusedSidebar";
import type { AgentFocusedShellViewProps } from "../containers/useAgentFocusedShellController";
import type { AgentResponse } from "@azents/public-client";
import type { ReactNode } from "react";

interface AgentFocusedShellProps {
  handle: string;
  agent: AgentResponse;
  children: ReactNode;
}

const AGENT_RAIL_WIDTH = rem(288);

export function AgentFocusedShell(
  props: AgentFocusedShellProps,
): React.ReactElement {
  return <AgentFocusedShellView {...useAgentFocusedShellController(props)} />;
}

export function AgentFocusedShellView({
  children,
  drawerOpened,
  closeDrawer,
  mobileNavContext,
  sidebarProps,
}: AgentFocusedShellViewProps): React.ReactElement {
  return (
    <AgentFocusedShellMobileNavProvider value={mobileNavContext}>
      <Drawer
        opened={drawerOpened}
        onClose={closeDrawer}
        hiddenFrom="lg"
        withCloseButton={false}
        padding={0}
        size={`min(85vw, ${rem(352)})`}
      >
        <AgentFocusedSidebar {...sidebarProps} onNavigate={closeDrawer} />
      </Drawer>
      <Group h="100%" mih={0} gap={0} align="stretch" wrap="nowrap">
        <Box
          visibleFrom="lg"
          w={AGENT_RAIL_WIDTH}
          miw={AGENT_RAIL_WIDTH}
          style={{
            borderRight: `${rem(1)} solid var(--mantine-color-default-border)`,
            overflow: "hidden",
          }}
        >
          <AgentFocusedSidebar {...sidebarProps} />
        </Box>
        <Box
          h="100%"
          mih={0}
          miw={0}
          flex={1}
          style={{
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          {children}
        </Box>
      </Group>
    </AgentFocusedShellMobileNavProvider>
  );
}
