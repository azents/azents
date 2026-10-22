import type { GoogleService } from "@azents/public-client";

const prefix = "https://www.googleapis.com/auth/";
const serviceScopes: Record<GoogleService, string[]> = {
  gmail: [
    "https://mail.google.com/",
    ...[
      "gmail.readonly",
      "gmail.compose",
      "gmail.modify",
      "gmail.send",
      "gmail.labels",
      "gmail.metadata",
      "gmail.settings.basic",
    ].map((scope) => prefix + scope),
  ],
  calendar: [
    "calendar.events.readonly",
    "calendar.calendarlist.readonly",
    "calendar.events.freebusy",
    "calendar.events",
    "calendar.app.created",
    "calendar.readonly",
    "calendar",
    "calendar.freebusy",
    "calendar.events.owned",
    "calendar.events.owned.readonly",
    "calendar.events.public.readonly",
    "calendar.calendars",
    "calendar.calendarlist",
  ].map((scope) => prefix + scope),
  drive: [
    "drive",
    "drive.readonly",
    "drive.file",
    "drive.metadata",
    "drive.metadata.readonly",
  ].map((scope) => prefix + scope),
};
/** Offer supported service permissions at Google consent; actual grants admit tools. */
export function googleScopesForServices(services: GoogleService[]): string[] {
  return Array.from(
    new Set([
      "openid",
      "email",
      ...services.flatMap((service) => serviceScopes[service]),
    ]),
  ).sort();
}
