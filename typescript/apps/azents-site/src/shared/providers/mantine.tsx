"use client";

import { MantineProvider } from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { theme } from "@/shared/theme";
import type { ReactNode } from "react";

type MantineColorScheme = "light" | "dark" | "auto";

interface AppMantineProviderProps {
  children: ReactNode;
  defaultColorScheme?: MantineColorScheme;
  forceColorScheme?: "light" | "dark";
}

export function AppMantineProvider({
  children,
  defaultColorScheme,
  forceColorScheme,
}: AppMantineProviderProps): ReactNode {
  return (
    <MantineProvider
      defaultColorScheme={defaultColorScheme}
      forceColorScheme={forceColorScheme}
      theme={theme}
    >
      <ModalsProvider>{children}</ModalsProvider>
    </MantineProvider>
  );
}
