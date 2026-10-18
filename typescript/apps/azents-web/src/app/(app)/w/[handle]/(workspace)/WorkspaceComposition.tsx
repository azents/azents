"use client";

import { AgentSidebarSection } from "@/features/agents/components/AgentSidebarSection";
import { WorkspaceShell } from "@/features/workspace/components/WorkspaceShell";
import type { ReactNode } from "react";

function renderAgentSection(props: {
  handle: string;
  onNavigate?: () => void;
}): ReactNode {
  return <AgentSidebarSection {...props} />;
}

export function WorkspaceComposition({
  handle,
  children,
}: {
  handle: string;
  children: ReactNode;
}): React.ReactElement {
  return (
    <WorkspaceShell handle={handle} renderAgentSection={renderAgentSection}>
      {children}
    </WorkspaceShell>
  );
}
