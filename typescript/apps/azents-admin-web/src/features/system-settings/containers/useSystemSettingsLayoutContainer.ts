"use client";

import { useHash } from "@mantine/hooks";
import { settingsSectionFromHash } from "../settings-navigation";
import type { SettingsSection } from "../settings-navigation";

export interface SystemSettingsLayoutInput {
  sections: Record<SettingsSection, React.ReactNode>;
}

export interface SystemSettingsLayoutProps extends SystemSettingsLayoutInput {
  activeSection: SettingsSection;
  onSectionChange: (value: string | null) => void;
}

export function useSystemSettingsLayoutContainer({
  sections,
}: SystemSettingsLayoutInput): SystemSettingsLayoutProps {
  const [hash, setHash] = useHash();
  return {
    sections,
    activeSection: settingsSectionFromHash(hash),
    onSectionChange: (value) => {
      if (value !== null) {
        setHash(`#${settingsSectionFromHash(`#${value}`)}`);
      }
    },
  };
}
