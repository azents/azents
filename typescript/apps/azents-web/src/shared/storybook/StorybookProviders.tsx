"use client";

import { ColorSchemeScript } from "@mantine/core";
import { useColorScheme } from "@mantine/hooks";
import { NextIntlClientProvider } from "next-intl";
import messages from "@/i18n/en-US-messages";
import { ColorModeProvider } from "@/shared/providers/color-mode";
import { LocaleProvider } from "@/shared/providers/locale";
import { AppMantineProvider } from "@/shared/providers/mantine";
import type { ColorModePreference } from "@/shared/lib/color-mode";
import type { ReactElement, ReactNode } from "react";

interface StorybookProvidersProps {
  children: ReactNode;
  colorScheme: ColorModePreference;
}

export function StorybookProviders({
  children,
  colorScheme,
}: StorybookProvidersProps): ReactElement {
  const systemColorScheme = useColorScheme("light", {
    getInitialValueInEffect: false,
  });
  const resolvedColorScheme =
    colorScheme === "system" ? systemColorScheme : colorScheme;

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
                className="storybook-surface"
                style={{
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
