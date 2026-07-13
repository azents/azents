"use client";

/**
 * Global app bar component.
 *
 * Left/right content changes based on auth state and current path:
 * - Unauthenticated: logo + ColorModeSwitcher
 * - Authenticated: logo (→ /workspaces) + ColorModeSwitcher + user menu
 * - Inside workspace: logo + @handle + ColorModeSwitcher + user menu
 */
import { ActionIcon, Box, Burger, Group, Menu, rem, Text } from "@mantine/core";
import {
  IconExternalLink,
  IconLogout,
  IconShieldLock,
  IconUser,
  IconUserCircle,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";
import { AppLogo } from "@/shared/components/AppLogo";
import { ColorModeSwitcher } from "@/shared/components/ColorModeSwitcher";
import { useSidebar } from "@/shared/providers/sidebar";
import { trpc } from "@/trpc/client";

interface AppBarProps {
  authStatus: "authenticated" | "unauthenticated";
}

/** Extract workspace handle from pathname */
function extractWorkspaceHandle(pathname: string): string | null {
  const match = pathname.match(/^\/w\/([^/]+)/);
  return match?.[1] ?? null;
}

export function AppBar({ authStatus }: AppBarProps): React.ReactElement {
  const t = useTranslations("appBar");
  const router = useRouter();
  const pathname = usePathname();
  const { opened: sidebarOpened, toggle: toggleSidebar } = useSidebar();
  const isAuthenticated = authStatus === "authenticated";
  const { data: adminAccess } = trpc.user.adminAccess.useQuery(
    {},
    {
      enabled: isAuthenticated,
      retry: false,
    },
  );
  const workspaceHandle = extractWorkspaceHandle(pathname);
  const isAgentDetailRoute = /^\/w\/[^/]+\/agents\/(?!new(?:\/|$))[^/]+/.test(
    pathname,
  );
  /** Whether page has workspace/account sidebar */
  const hasSidebar =
    (workspaceHandle !== null && !isAgentDetailRoute) ||
    pathname.startsWith("/account");

  const logoutMutation = trpc.auth.logout.useMutation({
    onSuccess: () => {
      router.push("/");
    },
  });

  const onLogout = useCallback((): void => {
    logoutMutation.mutate();
  }, [logoutMutation]);

  const onAccount = useCallback((): void => {
    router.push("/account");
  }, [router]);

  const logoHref = isAuthenticated ? "/workspaces" : "/";

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
            <Menu.Dropdown>
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
