"use client";

/**
 * Workspace sidebar navigation component.
 *
 * Agent-centric IA: Home/members (top) → Agent section (expandable, inline recent sessions)
 * → footer utilities (toolkits, workspace settings, profile).
 */
import { Divider, NavLink, Stack } from "@mantine/core";
import {
  IconHome2,
  IconLayoutGrid,
  IconSettings,
  IconTool,
  IconUserEdit,
  IconUsers,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AgentSidebarSection } from "@/features/agents/components/AgentSidebarSection";

interface WorkspaceSidebarProps {
  handle: string;
  /** Called on NavLink click (for closing Mobile Drawer) */
  onNavigate?: () => void;
}

export function WorkspaceSidebar({
  handle,
  onNavigate,
}: WorkspaceSidebarProps): React.ReactElement {
  const t = useTranslations("workspace.sidebar");
  const pathname = usePathname();
  const basePath = `/w/${handle}`;

  const isHome = pathname === basePath;
  const isMembers = pathname === `${basePath}/members`;
  const isToolkits = pathname.startsWith(`${basePath}/toolkits`);
  const isSettings = pathname === `${basePath}/settings`;
  const isProfile = pathname === `${basePath}/profile`;

  return (
    <Stack gap={0}>
      {/* Workspace list link is shown only in Mobile Drawer */}
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
        href={basePath}
        label={t("home")}
        leftSection={<IconHome2 size={18} />}
        active={isHome}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href={`${basePath}/members`}
        label={t("members")}
        leftSection={<IconUsers size={18} />}
        active={isMembers}
        onClick={onNavigate}
      />

      <Divider my="xs" />

      <AgentSidebarSection handle={handle} onNavigate={onNavigate} />

      <Divider my="xs" />

      <NavLink
        component={Link}
        href={`${basePath}/toolkits`}
        label={t("toolkits")}
        leftSection={<IconTool size={18} />}
        active={isToolkits}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href={`${basePath}/settings`}
        label={t("settings")}
        leftSection={<IconSettings size={18} />}
        active={isSettings}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href={`${basePath}/profile`}
        label={t("myProfile")}
        leftSection={<IconUserEdit size={18} />}
        active={isProfile}
        onClick={onNavigate}
      />
    </Stack>
  );
}
