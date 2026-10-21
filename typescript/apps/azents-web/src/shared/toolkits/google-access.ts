import type { GoogleService } from "@azents/public-client";

const prefix = "https://www.googleapis.com/auth/";
export interface GoogleRequestOption<Key extends string> {
  service: GoogleService;
  key: Key;
  scope: string;
}
function option<Key extends string>(
  service: GoogleService,
  scope: string,
  key: Key,
): GoogleRequestOption<Key> {
  return {
    service,
    key,
    scope: scope === "mail" ? "https://mail.google.com/" : prefix + scope,
  };
}
/** Request purposes are UI labels, not a second execution permission policy. */
export const googleRequestOptions = [
  option("gmail", "gmail.readonly", "gmailRead"),
  option("gmail", "gmail.compose", "gmailCompose"),
  option("gmail", "gmail.modify", "gmailModify"),
  option("gmail", "gmail.send", "gmailSend"),
  option("gmail", "gmail.labels", "gmailLabels"),
  option("gmail", "gmail.metadata", "gmailMetadata"),
  option("gmail", "gmail.settings.basic", "gmailSettings"),
  option("gmail", "mail", "gmailFull"),
  option("calendar", "calendar.events.readonly", "calendarRead"),
  option("calendar", "calendar.calendarlist.readonly", "calendarListRead"),
  option("calendar", "calendar.events.freebusy", "calendarAvailability"),
  option("calendar", "calendar.events", "calendarEdit"),
  option("calendar", "calendar.app.created", "calendarCreate"),
  option("calendar", "calendar.readonly", "calendarReadAll"),
  option("calendar", "calendar", "calendarFull"),
  option("calendar", "calendar.freebusy", "calendarFreebusy"),
  option("calendar", "calendar.events.owned", "calendarOwned"),
  option("calendar", "calendar.events.owned.readonly", "calendarOwnedRead"),
  option("calendar", "calendar.events.public.readonly", "calendarPublicRead"),
  option("calendar", "calendar.calendars", "calendarCalendars"),
  option("calendar", "calendar.calendarlist", "calendarListEdit"),
  option("drive", "drive", "driveFull"),
  option("drive", "drive.readonly", "driveRead"),
  option("drive", "drive.file", "driveAppFiles"),
  option("drive", "drive.metadata", "driveMetadata"),
  option("drive", "drive.metadata.readonly", "driveMetadataRead"),
];
export function googleDefaultScopes(service: GoogleService): string[] {
  switch (service) {
    case "gmail":
      return [prefix + "gmail.readonly"];
    case "calendar":
      return [
        prefix + "calendar.events.readonly",
        prefix + "calendar.calendarlist.readonly",
      ];
    case "drive":
      return [prefix + "drive.readonly"];
  }
}
export function googleScopesForServices(
  services: GoogleService[],
  scopes: string[],
): string[] {
  return Array.from(
    new Set([
      "openid",
      "email",
      ...scopes.filter((scope) =>
        googleRequestOptions.some(
          (option) =>
            option.scope === scope && services.includes(option.service),
        ),
      ),
    ]),
  ).sort();
}
