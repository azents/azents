"use client";

/** Agent session Projects page. */
import { Box } from "@mantine/core";
import { ProjectPanel } from "@/features/chat/workspace/components/ProjectPanel";
import { useWorkspacePanelContainer } from "@/features/chat/workspace/containers/useWorkspacePanelContainer";
import { AgentSessionHeader } from "./components/AgentSessionHeader";
import type { AgentResponse } from "@azents/public-client";

interface AgentProjectsPageProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
}

export function AgentProjectsPage({
  handle,
  agent,
  sessionId,
}: AgentProjectsPageProps): React.ReactElement {
  const workspacePanel = useWorkspacePanelContainer({
    handle,
    agentId: agent.id,
    sessionId,
  });

  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      <AgentSessionHeader handle={handle} agent={agent} sessionId={sessionId} />
      <Box p="lg" style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
        <ProjectPanel
          projectState={workspacePanel.projectState}
          projectPickerState={workspacePanel.projectPickerState}
          isProjectPickerOpen={workspacePanel.isProjectPickerOpen}
          onOpenProjectPicker={workspacePanel.onOpenProjectPicker}
          onCloseProjectPicker={workspacePanel.onCloseProjectPicker}
          onOpenProjectPickerDirectory={
            workspacePanel.onOpenProjectPickerDirectory
          }
          onSelectProjectPickerDirectory={
            workspacePanel.onSelectProjectPickerDirectory
          }
          onRefreshProjectPicker={workspacePanel.onRefreshProjectPicker}
          onStartRuntimeForProjectPicker={
            workspacePanel.onStartRuntimeForProjectPicker
          }
          onApproveRegistrationRequest={
            workspacePanel.onApproveRegistrationRequest
          }
          onRejectRegistrationRequest={
            workspacePanel.onRejectRegistrationRequest
          }
          onDeleteProject={workspacePanel.onDeleteProject}
        />
      </Box>
    </Box>
  );
}
