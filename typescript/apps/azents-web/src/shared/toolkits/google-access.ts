import type {
  GoogleGroupDefinition,
  GoogleService,
  GoogleServiceAccess,
  GoogleToolGroup,
} from "@azents/public-client";

export type GoogleGroupPreset = "read_only" | "assistant" | "full" | "clear";
const presets: Record<GoogleGroupPreset, GoogleToolGroup[]> = {
  read_only: [
    "gmail_read",
    "calendar_read",
    "calendar_availability",
    "drive_read",
  ],
  assistant: [
    "gmail_read",
    "gmail_drafts",
    "gmail_send",
    "gmail_organize",
    "calendar_read",
    "calendar_availability",
    "calendar_events",
    "drive_read",
    "drive_files",
  ],
  full: [
    "gmail_read",
    "gmail_labels",
    "gmail_drafts",
    "gmail_send",
    "gmail_organize",
    "gmail_filters",
    "calendar_read",
    "calendar_availability",
    "calendar_events",
    "calendar_status",
    "calendar_create",
    "drive_read",
    "drive_files",
    "drive_sharing",
    "drive_ownership",
  ],
  clear: [],
};
export const googleGroupPresets: GoogleGroupPreset[] = [
  "read_only",
  "assistant",
  "full",
  "clear",
];

export function googlePresetGroups(
  preset: GoogleGroupPreset,
  services: GoogleService[],
  catalog: GoogleGroupDefinition[],
): GoogleToolGroup[] {
  return catalog
    .filter(
      (group) =>
        services.includes(group.service) &&
        presets[preset].includes(group.group),
    )
    .map((group) => group.group)
    .sort();
}

export function googleScopesForGroups(
  groups: GoogleToolGroup[],
  catalog: GoogleGroupDefinition[],
): string[] {
  return Array.from(
    new Set([
      "openid",
      "email",
      ...catalog
        .filter((group) => groups.includes(group.group))
        .flatMap((group) => group.request_scopes),
    ]),
  ).sort();
}

export function googleGroupsUsable(
  services: GoogleService[],
  groups: GoogleToolGroup[],
  catalog: GoogleGroupDefinition[],
  accesses: GoogleServiceAccess[],
): boolean {
  return catalog.some(
    (group) =>
      groups.includes(group.group) &&
      services.includes(group.service) &&
      group.operations.some((operation) =>
        accesses.some(
          (access) =>
            access.service === group.service &&
            access.permitted_tools.includes(operation),
        ),
      ),
  );
}
