"use client";
import { useSidebar } from "@/shared/providers/sidebar";
import type { ReactNode } from "react";
interface AccountShellProps {
  children: ReactNode;
}

export interface AccountShellViewProps {
  children: AccountShellProps["children"];
  opened: boolean;
  close: () => void;
}
export function useAccountShellController({
  children,
}: AccountShellProps): AccountShellViewProps {
  const { opened, close } = useSidebar();
  return { children, opened, close };
}
