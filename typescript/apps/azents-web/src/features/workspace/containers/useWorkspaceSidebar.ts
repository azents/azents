"use client";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
export interface WorkspaceSidebarProps {
  handle: string;
  onNavigate?: () => void;
  renderAgentSection: (props: {
    handle: string;
    onNavigate?: () => void;
  }) => ReactNode;
}
export interface WorkspaceSidebarViewProps extends WorkspaceSidebarProps {
  pathname: string;
}
export function useWorkspaceSidebar(
  props: WorkspaceSidebarProps,
): WorkspaceSidebarViewProps {
  return { ...props, pathname: usePathname() };
}
