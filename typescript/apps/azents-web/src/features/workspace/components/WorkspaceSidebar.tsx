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
  IconPlugConnected,
  IconSettings,
  IconTool,
  IconUserEdit,
  IconUsers,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceSidebar } from "../containers/useWorkspaceSidebar";
import type { WorkspaceSidebarViewProps } from "../containers/useWorkspaceSidebar";

export const WorkspaceSidebar = createReactContainer(
  "WorkspaceSidebar",
  useWorkspaceSidebar,
  WorkspaceSidebarView,
);

export function WorkspaceSidebarView({
  handle,
  onNavigate,
  pathname,
  renderAgentSection,
}: WorkspaceSidebarViewProps): React.ReactElement {
  const t = useTranslations("workspace.sidebar");
  const basePath = `/w/${handle}`;

  const isHome = pathname === basePath;
  const isMembers = pathname === `${basePath}/members`;
  const isToolkits = pathname.startsWith(`${basePath}/toolkits`);
  const isExternalChannels = pathname.startsWith(`${basePath}/integrations`);
  const isSettings = pathname.startsWith(`${basePath}/settings`);
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

      {renderAgentSection({ handle, onNavigate })}

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
        href={`${basePath}/personal-tools`}
        label={t("personalTools")}
        leftSection={<IconPlugConnected size={18} />}
        active={pathname.startsWith(`${basePath}/personal-tools`)}
        onClick={onNavigate}
      />
      <NavLink
        component={Link}
        href={`${basePath}/integrations`}
        label={t("integrations")}
        leftSection={<IconPlugConnected size={18} />}
        active={isExternalChannels}
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
