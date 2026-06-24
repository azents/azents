"use client";

import { createContext, type ReactNode, useContext } from "react";
import type { PublicConfig } from "../config";

const ConfigContext = createContext<PublicConfig | null>(null);

interface ConfigProviderProps {
  config: PublicConfig;
  children: ReactNode;
}

export function ConfigProvider({
  config,
  children,
}: ConfigProviderProps): React.ReactElement {
  return (
    <ConfigContext.Provider value={config}>{children}</ConfigContext.Provider>
  );
}

export function useConfig(): PublicConfig {
  const config = useContext(ConfigContext);
  if (!config) {
    throw new Error("useConfig must be used within a ConfigProvider");
  }
  return config;
}
