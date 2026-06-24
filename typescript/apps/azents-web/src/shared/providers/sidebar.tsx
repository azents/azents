"use client";

/**
 * Sidebar drawer state context.
 *
 * Shares drawer open/close state between global AppBar (Burger button)
 * and WorkspaceShell (Drawer).
 */
import { useDisclosure } from "@mantine/hooks";
import { createContext, type ReactNode, useContext, useMemo } from "react";

interface SidebarContextValue {
  /** Whether Drawer is open */
  opened: boolean;
  /** Open Drawer */
  open: () => void;
  /** Close Drawer */
  close: () => void;
  /** Toggle Drawer open/close */
  toggle: () => void;
}

const SidebarContext = createContext<SidebarContextValue>({
  opened: false,
  open: () => {},
  close: () => {},
  toggle: () => {},
});

export const useSidebar = (): SidebarContextValue => useContext(SidebarContext);

export function SidebarProvider({
  children,
}: {
  children: ReactNode;
}): ReactNode {
  const [opened, { open, close, toggle }] = useDisclosure(false);

  const value = useMemo(
    () => ({ opened, open, close, toggle }),
    [opened, open, close, toggle],
  );

  return (
    <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>
  );
}
