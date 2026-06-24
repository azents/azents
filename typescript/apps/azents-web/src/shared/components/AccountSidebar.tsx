"use client";

/**
 * Account settings sidebar navigation component.
 *
 * NavLink list for moving between account settings pages.
 * Rendered as fixed sidebar on desktop and inside Drawer on mobile.
 */
import { Divider, NavLink, Stack } from "@mantine/core";
import {
  IconKey,
  IconLayoutGrid,
  IconShield,
  IconUser,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface AccountSidebarProps {
  /** Called on NavLink click (for closing mobile Drawer) */
  onNavigate?: () => void;
}

export function AccountSidebar({
  onNavigate,
}: AccountSidebarProps): React.ReactElement {
  const t = useTranslations("account.sidebar");
  const pathname = usePathname();

  const isAccount = pathname === "/account";
  const isSecurity = pathname === "/account/security";
  const isSignupTokens = pathname === "/account/signup-tokens";

  return (
    <Stack gap={0}>
      {/* Workspace list link is shown only in mobile Drawer */}
      {onNavigate && (
        <>
          <NavLink
            component={Link}
            href="/workspaces"
            label={t("workspaces")}
            leftSection={<IconLayoutGrid size={18} />}
            onClick={onNavigate}
          />
          <Divider my="xs" />
        </>
      )}
      <NavLink
        component={Link}
        href="/account"
        label={t("general")}
        leftSection={<IconUser size={18} />}
        active={isAccount}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href="/account/security"
        label={t("security")}
        leftSection={<IconShield size={18} />}
        active={isSecurity}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href="/account/signup-tokens"
        label="Signup tokens"
        leftSection={<IconKey size={18} />}
        active={isSignupTokens}
        onClick={onNavigate}
      />
    </Stack>
  );
}
