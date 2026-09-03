"use client";

import { createContext, useContext } from "react";
import type { ReactNode } from "react";

export interface AgentFocusedShellMobileNav {
  openAgentNavigation: () => void;
}

const AgentFocusedShellMobileNavContext =
  createContext<AgentFocusedShellMobileNav | null>(null);

interface AgentFocusedShellMobileNavProviderProps {
  children: ReactNode;
  value: AgentFocusedShellMobileNav;
}

export function AgentFocusedShellMobileNavProvider({
  children,
  value,
}: AgentFocusedShellMobileNavProviderProps): React.ReactElement {
  return (
    <AgentFocusedShellMobileNavContext.Provider value={value}>
      {children}
    </AgentFocusedShellMobileNavContext.Provider>
  );
}

export function useAgentFocusedShellMobileNav(): AgentFocusedShellMobileNav | null {
  return useContext(AgentFocusedShellMobileNavContext);
}
