"use client";

import { ColorSchemeScript } from "@mantine/core";
import { NextIntlClientProvider } from "next-intl";
import { useEffect, useState } from "react";
import { ColorModeProvider } from "@/shared/providers/color-mode";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import messages from "../../../messages/en-US.json";
import type { ColorModePreference } from "@/shared/lib/color-mode";
import type { ReactElement, ReactNode } from "react";

type ResolvedColorScheme = "light" | "dark";

interface StorybookProvidersProps {
  children: ReactNode;
  colorScheme: ColorModePreference;
}

function getSystemColorScheme(): ResolvedColorScheme {
  if (typeof window === "undefined") {
    return "light";
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

function resolveColorScheme(
  preference: ColorModePreference,
): ResolvedColorScheme {
  return preference === "system" ? getSystemColorScheme() : preference;
}

export function StorybookProviders({
  children,
  colorScheme,
}: StorybookProvidersProps): ReactElement {
  const [resolvedColorScheme, setResolvedColorScheme] =
    useState<ResolvedColorScheme>(() => resolveColorScheme(colorScheme));

  useEffect(() => {
    if (colorScheme !== "system") {
      setResolvedColorScheme(colorScheme);
      return;
    }

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const syncColorScheme = (): void => {
      setResolvedColorScheme(getSystemColorScheme());
    };

    syncColorScheme();
    mediaQuery.addEventListener("change", syncColorScheme);
    return () => mediaQuery.removeEventListener("change", syncColorScheme);
  }, [colorScheme]);

  return (
    <div className="storybook-root">
      <ColorSchemeScript forceColorScheme={resolvedColorScheme} />
      <NextIntlClientProvider locale="en-US" messages={messages}>
        <AppMantineProvider forceColorScheme={resolvedColorScheme}>
          <LocaleProvider locale="en-US">
            <ColorModeProvider
              key={`${colorScheme}-${resolvedColorScheme}`}
              initialPreference={colorScheme}
              initialResolvedMode={resolvedColorScheme}
            >
              <div
                style={{
                  minHeight: "100vh",
                  background: "var(--mantine-color-body)",
                  color: "var(--mantine-color-text)",
                }}
              >
                {children}
              </div>
            </ColorModeProvider>
          </LocaleProvider>
        </AppMantineProvider>
      </NextIntlClientProvider>
    </div>
  );
}
