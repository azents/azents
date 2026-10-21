"use client";

import { useHash } from "@mantine/hooks";
import { settingsSectionFromHash } from "@/shared/lib/admin-navigation";
import type { SettingsSection } from "@/shared/lib/admin-navigation";

export interface SystemSettingsLayoutInput {
  sections: Record<SettingsSection, React.ReactNode>;
}

export interface SystemSettingsLayoutProps extends SystemSettingsLayoutInput {
  activeSection: SettingsSection;
}

export function useSystemSettingsLayoutContainer({
  sections,
}: SystemSettingsLayoutInput): SystemSettingsLayoutProps {
  const [hash] = useHash();
  return { sections, activeSection: settingsSectionFromHash(hash) };
}
