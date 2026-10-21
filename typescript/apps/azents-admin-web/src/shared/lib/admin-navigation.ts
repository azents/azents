import {
  IconArchive,
  IconBrain,
  IconBrandGithub,
  IconBrandGoogle,
  IconBug,
  IconBuilding,
  IconFile,
  IconHistory,
  IconLinkPlus,
  IconMail,
  IconPlug,
  IconRefresh,
  IconServer,
  IconSettings,
  IconUser,
  IconUsersGroup,
} from "@tabler/icons-react";
import { getPublicRoutePath } from "./auth-policy.ts";
import type { TablerIcon } from "@tabler/icons-react";

export const SETTINGS_SECTIONS = [
  {
    value: "google",
    label: "Google",
    description:
      "Set up the OAuth application for Calendar, Drive and Gmail Toolkits.",
    Icon: IconBrandGoogle,
  },
  {
    value: "github",
    label: "GitHub",
    description:
      "Manage the Platform GitHub App, review pending changes and check its health.",
    Icon: IconBrandGithub,
  },
  {
    value: "accounts",
    label: "Account linking",
    description:
      "Configure Slack and Discord OAuth applications for user identity linking.",
    Icon: IconPlug,
  },
  {
    value: "files",
    label: "File transfers",
    description: "Set file and reply size limits for External Channels.",
    Icon: IconFile,
  },
  {
    value: "memory",
    label: "Memory",
    description: "Control execution limits for Historical Memory work.",
    Icon: IconBrain,
  },
  {
    value: "audit",
    label: "Audit log",
    description:
      "Review recorded System Settings changes without exposing secrets.",
    Icon: IconHistory,
  },
] as const;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["value"];

export function settingsSectionFromHash(hash: string): SettingsSection {
  return (
    SETTINGS_SECTIONS.find((section) => `#${section.value}` === hash)?.value ??
    "google"
  );
}

export const ADMIN_RESOURCES = [
  {
    name: "workspaces",
    list: "/workspaces",
    label: "Workspaces",
    group: "People & access",
    Icon: IconBuilding,
  },
  {
    name: "users",
    list: "/users",
    label: "Users",
    group: "People & access",
    Icon: IconUser,
  },
  {
    name: "workspace-members",
    list: "/workspace-members",
    label: "Workspace members",
    group: "People & access",
    Icon: IconUsersGroup,
  },
  {
    name: "verifications",
    list: "/verifications",
    label: "Email verifications",
    group: "People & access",
    Icon: IconMail,
  },
  {
    name: "signup-tokens",
    list: "/signup-tokens",
    label: "Signup links",
    group: "People & access",
    Icon: IconLinkPlus,
  },
  {
    name: "model-catalog",
    list: "/model-catalog",
    label: "Model catalog",
    group: "Platform",
    Icon: IconRefresh,
  },
  {
    name: "runtime-providers",
    list: "/runtime-providers",
    label: "Runtime providers",
    group: "Platform",
    Icon: IconServer,
  },
  {
    name: "retention",
    list: "/retention",
    label: "Retention",
    group: "Platform",
    Icon: IconArchive,
  },
  {
    name: "system-settings",
    list: "/system-settings",
    label: "System Settings",
    group: "Settings",
    Icon: IconSettings,
  },
  {
    name: "debug",
    list: "/debug",
    label: "Debug",
    group: "Diagnostics",
    Icon: IconBug,
  },
] as const;

export interface AdminNavigationItem {
  key: string;
  label: string;
  href: string;
  active: boolean;
  Icon: TablerIcon;
}

export interface AdminNavigationGroup {
  label: string;
  items: AdminNavigationItem[];
}

export interface AdminLocation {
  group: string;
  label: string;
}

export function adminRouteMatches(pathname: string, path: string): boolean {
  return pathname === path || pathname.startsWith(`${path}/`);
}

export function adminNavigation(
  publicBaseUrl: string,
  pathname: string,
  hash: string,
): { groups: AdminNavigationGroup[]; location: AdminLocation } {
  const groups: AdminNavigationGroup[] = [];
  let location: AdminLocation = { group: "Administration", label: "Overview" };
  for (const resource of ADMIN_RESOURCES) {
    const href = getPublicRoutePath(publicBaseUrl, resource.list);
    const active =
      adminRouteMatches(pathname, href) ||
      adminRouteMatches(pathname, resource.list);
    let group = groups.find((item) => item.label === resource.group);
    if (!group) {
      group = { label: resource.group, items: [] };
      groups.push(group);
    }
    if (resource.name === "system-settings") {
      const selected = settingsSectionFromHash(hash);
      for (const section of SETTINGS_SECTIONS) {
        const isActive = active && selected === section.value;
        group.items.push({
          key: `settings-${section.value}`,
          label: section.label,
          href: `${href}#${section.value}`,
          active: isActive,
          Icon: section.Icon,
        });
        if (isActive) {
          location = { group: resource.group, label: section.label };
        }
      }
    } else {
      group.items.push({
        key: resource.name,
        label: resource.label,
        href,
        active,
        Icon: resource.Icon,
      });
      if (active) {
        location = { group: resource.group, label: resource.label };
      }
    }
  }
  return { groups, location };
}
