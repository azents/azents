"use client";

import { useSearchParams } from "next/navigation";
import { settingsSectionFromValue } from "@/shared/lib/admin-navigation";
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
  const sectionValue = useSearchParams().get("section");
  return { sections, activeSection: settingsSectionFromValue(sectionValue) };
}
