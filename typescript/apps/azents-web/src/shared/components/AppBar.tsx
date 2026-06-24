"use client";

/**
 * Global app bar component.
 *
 * Left/right content changes based on auth state and current path:
 * - Unauthenticated: logo + ColorModeSwitcher
 * - Authenticated: logo (→ /workspaces) + ColorModeSwitcher + user menu
 * - Inside workspace: logo + @handle + ColorModeSwitcher + user menu
 */
import { ActionIcon, Box, Burger, Group, Menu, Text } from "@mantine/core";
import { IconLogout, IconUser, IconUserCircle } from "@tabler/icons-react";
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
  const workspaceHandle = extractWorkspaceHandle(pathname);
  /** Whether page has sidebar (workspace or account settings) */
  const hasSidebar =
    workspaceHandle !== null || pathname.startsWith("/account");

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
                <IconUserCircle size={24} />
              </ActionIcon>
            </Menu.Target>
            <Menu.Dropdown>
              <Menu.Item
                leftSection={<IconUser size={16} />}
                onClick={onAccount}
              >
                {t("account")}
              </Menu.Item>
              <Menu.Divider />
              <Menu.Item
                leftSection={<IconLogout size={16} />}
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
