"use client";

import { usePathname } from "next/navigation";

export interface AccountSidebarInput {
  onNavigate?: () => void;
}

export interface AccountSidebarOutput extends AccountSidebarInput {
  pathname: string;
}

export function useAccountSidebarController(
  props: AccountSidebarInput,
): AccountSidebarOutput {
  return { ...props, pathname: usePathname() };
}
