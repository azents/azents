"use client";

/** Shared visual shell for entity settings overview and detail pages. */

import { Box, Button, Group, rem } from "@mantine/core";
import { IconArrowLeft } from "@tabler/icons-react";
import Link from "next/link";
import type { ReactNode } from "react";

interface SettingsPageLayoutProps {
  header: ReactNode;
  backHref: string;
  backLabel: string;
  children: ReactNode;
  backMaxWidth?: string;
}

export function SettingsPageLayout({
  header,
  backHref,
  backLabel,
  children,
  backMaxWidth = rem(960),
}: SettingsPageLayoutProps): React.ReactElement {
  return (
    <Box h="100%" mih={0} style={{ display: "flex", flexDirection: "column" }}>
      {header}
      <Box
        style={{
          borderBottom: "0.0625rem solid var(--mantine-color-default-border)",
          backgroundColor: "var(--mantine-color-body)",
        }}
      >
        <Group px="md" py="xs" maw={backMaxWidth} mx="auto" w="100%">
          <Button
            component={Link}
            href={backHref}
            variant="subtle"
            leftSection={<IconArrowLeft size={rem(16)} />}
          >
            {backLabel}
          </Button>
        </Group>
      </Box>
      <Box
        style={{
          display: "flex",
          flex: 1,
          flexDirection: "column",
          minHeight: 0,
        }}
      >
        {children}
      </Box>
    </Box>
  );
}
