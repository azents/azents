"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useBrowserEnabled } from "./BrowserAvailability";
import {
  browserPanelHref,
  browserToolTarget,
  isBrowserSessionPath,
} from "./route";
export interface BrowserToolResultLinkProps {
  name: string;
  result: string | null;
}
export function useBrowserToolResultLink({
  name,
  result,
}: BrowserToolResultLinkProps): { href: string | null } {
  const pathname = usePathname();
  const enabled = useBrowserEnabled();
  const search = useSearchParams();
  const target = browserToolTarget(name, result);
  return {
    href:
      !enabled || target === null || !isBrowserSessionPath(pathname)
        ? null
        : browserPanelHref(pathname, search.toString(), target),
  };
}
