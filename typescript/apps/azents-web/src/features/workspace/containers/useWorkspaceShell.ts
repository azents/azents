"use client";
import { useSidebar } from "@/shared/providers/sidebar";
import type { WorkspaceSidebarProps } from "./useWorkspaceSidebar";
import type { ReactNode } from "react";
export interface WorkspaceShellProps {
  handle: string;
  children: ReactNode;
  renderAgentSection: WorkspaceSidebarProps["renderAgentSection"];
}
export interface WorkspaceShellViewProps extends WorkspaceShellProps {
  opened: boolean;
  close: () => void;
}
export function useWorkspaceShell(
  props: WorkspaceShellProps,
): WorkspaceShellViewProps {
  const { opened, close } = useSidebar();
  return { ...props, opened, close };
}
