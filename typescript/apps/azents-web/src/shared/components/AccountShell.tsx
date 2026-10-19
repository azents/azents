"use client";
import { Box, Drawer, Group, rem } from "@mantine/core";
/**
 * Account settings shell component.
 *
 * Desktop: fixed left sidebar + right content area.
 * Mobile: toggle Drawer sidebar with AppBar Burger.
 */
import { AccountSidebar } from "@/shared/components/AccountSidebar";

import { useAccountShellController } from "../containers/useAccountShellController";
import type { AccountShellViewProps } from "../containers/useAccountShellController";
import type { ReactNode } from "react";

interface AccountShellProps {
  children: ReactNode;
}

/** Sidebar width. */
const SIDEBAR_WIDTH = rem(250);

export function AccountShell(props: AccountShellProps): React.ReactElement {
  return <AccountShellView {...useAccountShellController(props)} />;
}

export function AccountShellView({
  children,
  opened,
  close,
}: AccountShellViewProps): React.ReactElement {
  return (
    <>
      {/* Mobile Drawer */}
      <Drawer
        opened={opened}
        onClose={close}
        size={SIDEBAR_WIDTH}
        hiddenFrom="sm"
        withCloseButton={false}
        padding="sm"
      >
        <AccountSidebar onNavigate={close} />
      </Drawer>

      {/* Main layout — ensure full height */}
      <Group
        align="stretch"
        gap={0}
        wrap="nowrap"
        style={{
          flex: 1,
          minHeight: "calc(100dvh - var(--app-shell-header-offset, 0rem))",
        }}
      >
        {/* Desktop sidebar */}
        <Box
          visibleFrom="sm"
          style={{
            width: SIDEBAR_WIDTH,
            minWidth: SIDEBAR_WIDTH,
            borderRight: `${rem(1)} solid var(--mantine-color-default-border)`,
          }}
          py="sm"
        >
          <AccountSidebar />
        </Box>

        {/* Content area */}
        <Box style={{ flex: 1, minWidth: 0 }}>{children}</Box>
      </Group>
    </>
  );
}
