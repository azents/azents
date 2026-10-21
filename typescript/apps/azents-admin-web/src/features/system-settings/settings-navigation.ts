export const SETTINGS_SECTIONS = [
  {
    value: "google",
    label: "Google",
    description:
      "Set up the OAuth application for Calendar, Drive and Gmail Toolkits.",
  },
  {
    value: "github",
    label: "GitHub",
    description:
      "Manage the Platform GitHub App, review pending changes and check its health.",
  },
  {
    value: "accounts",
    label: "Account linking",
    description:
      "Configure Slack and Discord OAuth applications for user identity linking.",
  },
  {
    value: "files",
    label: "File transfers",
    description: "Set file and reply size limits for External Channels.",
  },
  {
    value: "memory",
    label: "Memory",
    description: "Control execution limits for Historical Memory work.",
  },
  {
    value: "audit",
    label: "Audit log",
    description:
      "Review recorded System Settings changes without exposing secrets.",
  },
] as const;

export type SettingsSection = (typeof SETTINGS_SECTIONS)[number]["value"];

export function settingsSectionFromHash(hash: string): SettingsSection {
  return (
    SETTINGS_SECTIONS.find((section) => `#${section.value}` === hash)?.value ??
    "google"
  );
}
