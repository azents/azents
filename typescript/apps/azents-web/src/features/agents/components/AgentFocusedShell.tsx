"use client";

/**
 * Agent-focused route shell.
 *
 * Removes the workspace-wide sidebar from Agent detail screens and gives Agent
 * work a dedicated left rail plus mobile drawer entry point.
 */
import { Box, Drawer, Group, rem } from "@mantine/core";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AgentFocusedShellMobileNavProvider } from "@/shared/agent-session/AgentFocusedShellMobileNav";
import { trpc } from "@/trpc/client";
import {
  AgentFocusedSidebar,
  type AgentFocusedSidebarUser,
  type AgentSessionListScope,
} from "./AgentFocusedSidebar";
import type { AgentResponse } from "@azents/public-client";
import type { ReactNode } from "react";

interface AgentFocusedShellProps {
  handle: string;
  agent: AgentResponse;
  children: ReactNode;
}

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

function parseSessionListScope(
  value: string | null,
): AgentSessionListScope | null {
  if (value === "team" || value === "user") {
    return value;
  }
  return null;
}

export function AgentFocusedShell({
  handle,
  agent,
  children,
}: AgentFocusedShellProps): React.ReactElement {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const utils = trpc.useUtils();
  const [drawerOpened, setDrawerOpened] = useState(false);
  const [sessionListScope, setSessionListScope] =
    useState<AgentSessionListScope>("team");
  const closeDrawer = (): void => setDrawerOpened(false);
  const openDrawer = useCallback((): void => setDrawerOpened(true), []);
  const activeSessionId = useMemo(
    () => extractSessionId(pathname, agent.id),
    [pathname, agent.id],
  );
  const draftScope = useMemo(() => {
    if (activeSessionId !== "new") {
      return null;
    }
    return parseSessionListScope(searchParams.get("scope"));
  }, [activeSessionId, searchParams]);

  const sessionSidebarQuery = trpc.chat.getAgentSessionSidebar.useQuery(
    {
      agentId: agent.id,
    },
    {
      refetchInterval: 5_000,
      staleTime: 0,
    },
  );
  const activeSessionQuery = trpc.chat.getAgentSession.useQuery(
    {
      agentId: agent.id,
      sessionId: activeSessionId ?? "",
    },
    {
      enabled: activeSessionId !== null && activeSessionId !== "new",
      staleTime: 0,
    },
  );
  const userSessionsQuery = trpc.chat.listAgentUserSessions.useQuery(
    { agentId: agent.id },
    {
      enabled: sessionListScope === "user",
      refetchInterval: sessionListScope === "user" ? 5_000 : false,
      staleTime: 0,
    },
  );
  const meQuery = trpc.user.me.useQuery(void 0, { retry: false });
  const profileQuery = trpc.memberProfile.getMyProfile.useQuery(
    { handle },
    { retry: false },
  );
  const adminAccessQuery = trpc.user.adminAccess.useQuery({}, { retry: false });
  const logoutMutation = trpc.auth.logout.useMutation({
    onSuccess: () => {
      closeDrawer();
      router.push("/");
    },
  });
  const updateTitleMutation = trpc.chat.updateAgentSessionTitle.useMutation();
  const updatePinMutation = trpc.chat.updateAgentSessionPin.useMutation({
    onSuccess: (_result, variables) => {
      void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
      void utils.chat.getAgentSessionSidebar.invalidate({ agentId: agent.id });
      void utils.chat.listAgentUserSessions.invalidate({ agentId: agent.id });
      void utils.chat.getAgentSession.invalidate({
        agentId: agent.id,
        sessionId: variables.sessionId,
      });
    },
  });
  const archiveSessionMutation = trpc.chat.archiveAgentSession.useMutation({
    onSuccess: (_result, variables) => {
      void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
      void utils.chat.getAgentSessionSidebar.invalidate({ agentId: agent.id });
      void utils.chat.listAgentUserSessions.invalidate({ agentId: agent.id });
      closeDrawer();
      if (activeSessionId === variables.sessionId) {
        const draftPath =
          sessionListScope === "user"
            ? `/w/${handle}/agents/${agent.id}/sessions/new?scope=user`
            : `/w/${handle}/agents/${agent.id}/sessions/new`;
        router.replace(draftPath);
      }
    },
  });
  const handleCreateSession = useCallback((): void => {
    closeDrawer();
    if (sessionListScope === "user") {
      router.push(`/w/${handle}/agents/${agent.id}/sessions/new?scope=user`);
      return;
    }
    router.push(`/w/${handle}/agents/${agent.id}/sessions/new`);
  }, [agent.id, handle, router, sessionListScope]);

  const handleSessionListScopeChange = useCallback(
    (scope: AgentSessionListScope): void => {
      setSessionListScope(scope);
    },
    [],
  );

  useEffect(() => {
    if (draftScope !== null) {
      setSessionListScope(draftScope);
      return;
    }
    if (activeSessionId === null || activeSessionId === "new") {
      return;
    }
    if (activeSessionQuery.data?.product_mode === "user") {
      setSessionListScope("user");
      return;
    }
    if (activeSessionQuery.data?.product_mode === "team") {
      setSessionListScope("team");
    }
  }, [activeSessionId, activeSessionQuery.data?.product_mode, draftScope]);

  const handleRenameSession = useCallback(
    async (sessionId: string, title: string | null): Promise<void> => {
      await updateTitleMutation.mutateAsync({
        agentId: agent.id,
        sessionId,
        title,
      });
      if (sessionListScope === "user") {
        void utils.chat.listAgentUserSessions.invalidate({ agentId: agent.id });
      } else {
        void utils.chat.listAgentSessions.invalidate({ agentId: agent.id });
        void utils.chat.getAgentSessionSidebar.invalidate({
          agentId: agent.id,
        });
      }
      void utils.chat.getAgentSession.invalidate({
        agentId: agent.id,
        sessionId,
      });
    },
    [
      agent.id,
      sessionListScope,
      updateTitleMutation,
      utils.chat.getAgentSession,
      utils.chat.getAgentSessionSidebar,
      utils.chat.listAgentSessions,
      utils.chat.listAgentUserSessions,
    ],
  );

  const handleArchiveSession = useCallback(
    (sessionId: string): void => {
      archiveSessionMutation.reset();
      archiveSessionMutation.mutate({ agentId: agent.id, sessionId });
    },
    [archiveSessionMutation, agent.id],
  );

  const handleSetSessionPinned = useCallback(
    (sessionId: string, pinned: boolean): void => {
      updatePinMutation.reset();
      updatePinMutation.mutate({ agentId: agent.id, sessionId, pinned });
    },
    [agent.id, updatePinMutation],
  );

  const handleLogout = useCallback((): void => {
    logoutMutation.mutate();
  }, [logoutMutation]);

  const currentUser = useMemo<AgentFocusedSidebarUser | null>(() => {
    const email = meQuery.data?.email;
    if (!email) {
      return null;
    }
    return {
      email,
      name: profileQuery.data?.name.trim() || email,
    };
  }, [meQuery.data?.email, profileQuery.data?.name]);

  const mobileNavContext = useMemo(
    () => ({ openAgentNavigation: openDrawer }),
    [openDrawer],
  );

  const teamPinnedSessions = sessionSidebarQuery.data?.pinned ?? [];
  const teamRecentSessions = sessionSidebarQuery.data?.recent ?? [];
  const userSessions = userSessionsQuery.data?.items ?? [];
  const sessionsLoading =
    sessionListScope === "user"
      ? userSessionsQuery.isPending
      : sessionSidebarQuery.isPending;
  const sessionsError =
    (sessionListScope === "user"
      ? userSessionsQuery.error?.message
      : sessionSidebarQuery.error?.message) ??
    updatePinMutation.error?.message ??
    archiveSessionMutation.error?.message ??
    null;
  const sidebarProps = {
    handle,
    agent,
    currentUser,
    adminAccessUrl: adminAccessQuery.data?.url ?? null,
    loggingOut: logoutMutation.isPending,
    onLogout: handleLogout,
    sessionListScope,
    onSessionListScopeChange: handleSessionListScopeChange,
    sessions: sessionListScope === "user" ? userSessions : [],
    pinnedSessions: sessionListScope === "team" ? teamPinnedSessions : [],
    recentSessions: sessionListScope === "team" ? teamRecentSessions : [],
    sessionsLoading,
    sessionsError,
    activeSessionId,
    creatingSession: false,
    renamingSessionId: updateTitleMutation.isPending
      ? updateTitleMutation.variables.sessionId
      : null,
    archivingSessionId: archiveSessionMutation.isPending
      ? archiveSessionMutation.variables.sessionId
      : null,
    pinningSessionId: updatePinMutation.isPending
      ? updatePinMutation.variables.sessionId
      : null,
    onCreateSession: handleCreateSession,
    onRenameSession: handleRenameSession,
    onArchiveSession: handleArchiveSession,
    onSetSessionPinned: handleSetSessionPinned,
  };

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
