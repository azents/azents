"use client";

/**
 * Agent-focused route shell.
 *
 * Removes the workspace-wide sidebar from Agent detail screens and gives Agent
 * work a dedicated left rail plus mobile drawer entry point.
 */
import { Box, Drawer, Group, rem } from "@mantine/core";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { trpc } from "@/trpc/client";
import { AgentFocusedSidebar } from "./AgentFocusedSidebar";
import type { AgentResponse } from "@azents/public-client";
import type { ReactNode } from "react";

interface AgentFocusedShellProps {
  handle: string;
  agent: AgentResponse;
  children: ReactNode;
}

interface AgentFocusedShellMobileNavContextValue {
  openAgentNavigation: () => void;
}

const AgentFocusedShellMobileNavContext =
  createContext<AgentFocusedShellMobileNavContextValue | null>(null);

const AGENT_RAIL_WIDTH = rem(288);

function extractSessionId(pathname: string, agentId: string): string | null {
  const marker = `/agents/${agentId}/sessions/`;
  const markerIndex = pathname.indexOf(marker);
  if (markerIndex === -1) {
    return null;
  }
  const tail = pathname.slice(markerIndex + marker.length);
  return tail.split("/")[0] ?? null;
}

export function AgentFocusedShell({
  handle,
  agent,
  children,
}: AgentFocusedShellProps): React.ReactElement {
  const router = useRouter();
  const pathname = usePathname();
  const utils = trpc.useUtils();
  const [drawerOpened, setDrawerOpened] = useState(false);
  const closeDrawer = (): void => setDrawerOpened(false);
  const openDrawer = useCallback((): void => setDrawerOpened(true), []);
  const activeSessionId = useMemo(
    () => extractSessionId(pathname, agent.id),
    [pathname, agent.id],
  );

  const sessionsQuery = trpc.chat.listAgentSessions.useQuery({
    agentId: agent.id,
  });
  const createSessionMutation = trpc.chat.createTeamAgentSession.useMutation({
    onSuccess: (session) => {
      void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
      closeDrawer();
      router.push(`/w/${handle}/agents/${agent.id}/sessions/${session.id}`);
    },
  });

  const handleCreateSession = useCallback((): void => {
    createSessionMutation.mutate({ agentId: agent.id });
  }, [createSessionMutation, agent.id]);

  const mobileNavContext = useMemo(
    () => ({ openAgentNavigation: openDrawer }),
    [openDrawer],
  );

  return (
    <AgentFocusedShellMobileNavContext.Provider value={mobileNavContext}>
      <Drawer
        opened={drawerOpened}
        onClose={closeDrawer}
        hiddenFrom="lg"
        withCloseButton={false}
        padding={0}
        size={`min(85vw, ${rem(352)})`}
      >
        <AgentFocusedSidebar
          handle={handle}
          agent={agent}
          sessions={sessionsQuery.data?.items ?? []}
          sessionsLoading={sessionsQuery.isPending}
          sessionsError={sessionsQuery.error?.message ?? null}
          activeSessionId={activeSessionId}
          creatingSession={createSessionMutation.isPending}
          onCreateSession={handleCreateSession}
          onNavigate={closeDrawer}
        />
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
          <AgentFocusedSidebar
            handle={handle}
            agent={agent}
            sessions={sessionsQuery.data?.items ?? []}
            sessionsLoading={sessionsQuery.isPending}
            sessionsError={sessionsQuery.error?.message ?? null}
            activeSessionId={activeSessionId}
            creatingSession={createSessionMutation.isPending}
            onCreateSession={handleCreateSession}
          />
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
    </AgentFocusedShellMobileNavContext.Provider>
  );
}

export function useAgentFocusedShellMobileNav(): AgentFocusedShellMobileNavContextValue | null {
  return useContext(AgentFocusedShellMobileNavContext);
}
