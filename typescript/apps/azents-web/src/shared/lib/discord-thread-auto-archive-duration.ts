import type { DiscordThreadAutoArchiveDurationMinutes } from "@azents/public-client";

export const DEFAULT_DISCORD_THREAD_AUTO_ARCHIVE_DURATION: DiscordThreadAutoArchiveDurationMinutes = 1440;

export function isDiscordThreadAutoArchiveDuration(
  value: unknown,
): value is DiscordThreadAutoArchiveDurationMinutes {
  return value === 60 || value === 1440 || value === 4320 || value === 10080;
}

export function discordThreadAutoArchiveDurationFromConfiguration(
  providerConfiguration: unknown,
): DiscordThreadAutoArchiveDurationMinutes {
  if (
    typeof providerConfiguration !== "object" ||
    providerConfiguration === null ||
    !("thread_auto_archive_duration_minutes" in providerConfiguration)
  ) {
    return DEFAULT_DISCORD_THREAD_AUTO_ARCHIVE_DURATION;
  }
  const value = providerConfiguration.thread_auto_archive_duration_minutes;
  return isDiscordThreadAutoArchiveDuration(value)
    ? value
    : DEFAULT_DISCORD_THREAD_AUTO_ARCHIVE_DURATION;
}

export function discordThreadAutoArchiveDurationFromSelectValue(
  value: string | null,
): DiscordThreadAutoArchiveDurationMinutes | null {
  switch (value) {
    case "60":
      return 60;
    case "1440":
      return 1440;
    case "4320":
      return 4320;
    case "10080":
      return 10080;
    default:
      return null;
  }
}
