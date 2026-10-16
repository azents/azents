"use client";

import { createContext, useContext } from "react";
import type { ReactNode } from "react";

const BrowserEnabledContext = createContext(false);

/** Share the current Agent flag with deep Browser entry points, not input authority. */
export function BrowserAvailabilityProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: ReactNode;
}): ReactNode {
  return (
    <BrowserEnabledContext.Provider value={enabled}>
      {children}
    </BrowserEnabledContext.Provider>
  );
}

export function useBrowserEnabled(): boolean {
  return useContext(BrowserEnabledContext);
}
