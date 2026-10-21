"use client";

/**
 * Account settings sidebar navigation component.
 *
 * NavLink list for moving between account settings pages.
 * Rendered as fixed sidebar on desktop and inside Drawer on mobile.
 */
import { Divider, NavLink, rem, Stack } from "@mantine/core";
import {
  IconLayoutGrid,
  IconPlugConnected,
  IconShield,
  IconUser,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useAccountSidebarController } from "../containers/useAccountSidebarController";
import { createReactContainer } from "../lib/createReactContainer";
import type { AccountSidebarOutput } from "../containers/useAccountSidebarController";

export const AccountSidebar = createReactContainer(
  "AccountSidebar",
  useAccountSidebarController,
  AccountSidebarView,
);

export function AccountSidebarView({
  onNavigate,
  pathname,
}: AccountSidebarOutput): React.ReactElement {
  const t = useTranslations("account.sidebar");

  const isAccount = pathname === "/account";
  const isExternalAccounts = pathname === "/account/external-accounts";
  const isSecurity = pathname === "/account/security";

  return (
    <Stack gap={0}>
      {/* Workspace list link is shown only in mobile Drawer */}
      {onNavigate && (
        <>
          <NavLink
            component={Link}
            href="/workspaces"
            label={t("workspaces")}
            leftSection={<IconLayoutGrid size={rem(18)} />}
            onClick={onNavigate}
          />
          <Divider my="xs" />
        </>
      )}
      <NavLink
        component={Link}
        href="/account"
        label={t("general")}
        leftSection={<IconUser size={rem(18)} />}
        active={isAccount}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href="/account/external-accounts"
        label={t("externalAccounts")}
        leftSection={<IconPlugConnected size={rem(18)} />}
        active={isExternalAccounts}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href="/account/security"
        label={t("security")}
        leftSection={<IconShield size={rem(18)} />}
        active={isSecurity}
        onClick={onNavigate}
      />
    </Stack>
  );
}
