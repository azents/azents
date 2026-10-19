"use client";
import { ActionIcon, Box, Burger, Group, Menu, rem, Text } from "@mantine/core";
import {
  IconExternalLink,
  IconLogout,
  IconShieldLock,
  IconUser,
  IconUserCircle,
} from "@tabler/icons-react";
/**
 * Global app bar component.
 *
 * Left/right content changes based on auth state and current path:
 * - Unauthenticated: logo + ColorModeSwitcher
 * - Authenticated: logo (→ /workspaces) + ColorModeSwitcher + user menu
 * - Inside workspace: logo + @handle + ColorModeSwitcher + user menu
 */
import { AppLogo } from "@/shared/components/AppLogo";
import { ColorModeSwitcher } from "@/shared/components/ColorModeSwitcher";
import { useAppBarController } from "../containers/useAppBarController";
import type { AppBarViewProps } from "../containers/useAppBarController";

interface AppBarProps {
  authStatus: "authenticated" | "unauthenticated";
}

export function AppBar(props: AppBarProps): React.ReactElement {
  return <AppBarView {...useAppBarController(props)} />;
}

export function AppBarView({
  t,
  sidebarOpened,
  toggleSidebar,
  isAuthenticated,
  adminAccess,
  adminAccessPending,
  workspaceHandle,
  hasSidebar,
  logoutMutation,
  onLogout,
  onAccount,
  logoHref,
}: AppBarViewProps): React.ReactElement {
  return (
    <Group h="100%" px="md" justify="space-between">
      <Group gap="sm">
        {/* Desktop: always logo */}
        <Box visibleFrom="sm">
          <AppLogo href={logoHref} />
        </Box>
        {/* Mobile: Burger on sidebar pages, otherwise logo */}
        <Box hiddenFrom="sm">
          {hasSidebar ? (
            <Burger opened={sidebarOpened} onClick={toggleSidebar} size="sm" />
          ) : (
            <AppLogo href={logoHref} />
          )}
        </Box>
        {workspaceHandle && (
          <Text c="dimmed" size="sm">
            @{workspaceHandle}
          </Text>
        )}
      </Group>

      <Group gap="sm">
        <ColorModeSwitcher />
        {isAuthenticated && (
          <Menu shadow="md" width={200} position="bottom-end">
            <Menu.Target>
              <ActionIcon variant="subtle" size="lg" radius="xl">
                <IconUserCircle size={rem(24)} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown aria-busy={adminAccessPending}>
              <Menu.Item
                leftSection={<IconUser size={rem(16)} />}
                onClick={onAccount}
              >
                {t("account")}
              </Menu.Item>
              {adminAccess?.url && (
                <Menu.Item
                  component="a"
                  href={adminAccess.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  leftSection={<IconShieldLock size={rem(16)} />}
                  rightSection={<IconExternalLink size={rem(14)} />}
                >
                  {t("admin")}
                </Menu.Item>
              )}
              <Menu.Divider />
              <Menu.Item
                leftSection={<IconLogout size={rem(16)} />}
                onClick={onLogout}
                disabled={logoutMutation.isPending}
              >
                {t("logout")}
              </Menu.Item>
            </Menu.Dropdown>
          </Menu>
        )}
      </Group>
    </Group>
  );
}
