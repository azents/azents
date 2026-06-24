"use client";

/**
 * Mantine theme provider.
 *
 * variantColorResolver contains a function, so Server Component cannot pass
 * theme directly to MantineProvider. This provider is separated as a Client
 * Component to provide the theme.
 */
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
      theme={theme}
      defaultColorScheme={defaultColorScheme}
      forceColorScheme={forceColorScheme}
    >
      <ModalsProvider>{children}</ModalsProvider>
    </MantineProvider>
  );
}
