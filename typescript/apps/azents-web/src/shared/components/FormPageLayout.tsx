"use client";

/**
 * Form page layout.
 *
 * Common layout used by single-form-centered pages such as auth/onboarding.
 * - Place content vertically/horizontally centered
 * - Desktop (xs and above): card shape (border, background, border-radius)
 * - Mobile (below xs): content uses full screen without card
 * - Use color mode from (app) root layout as-is (reflect user settings)
 * - ColorModeSwitcher provided by global AppBar
 * - Optional header slot (StepIndicator, etc.)
 */
import { Box, rem } from "@mantine/core";
import type { ReactNode } from "react";

interface FormPageLayoutProps {
  children: ReactNode;
  /** Header element to show above form (for example, StepIndicator) */
  header?: ReactNode;
}

export function FormPageLayout({
  children,
  header,
}: FormPageLayoutProps): React.ReactElement {
  return (
    <Box
      style={{
        display: "flex",
        minHeight: "calc(100dvh - var(--app-shell-header-offset, 0px))",
        alignItems: "center",
        justifyContent: "center",
        paddingTop: rem(32),
        paddingBottom: rem(32),
      }}
    >
      <Box
        style={{
          display: "flex",
          width: "100%",
          flexDirection: "column",
          alignItems: "center",
          gap: rem(24),
        }}
      >
        {header}

        <Box
          style={{
            width: "100%",
            maxWidth: rem(500),
            margin: "0 auto",
            paddingLeft: rem(32),
            paddingRight: rem(32),
          }}
        >
          {children}
        </Box>
      </Box>
    </Box>
  );
}
