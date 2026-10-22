import { googleScopesForGroups } from "./google-access.ts";
import type {
  GoogleGroupDefinition,
  GoogleService,
  GoogleToolGroup,
} from "@azents/public-client";

export function googleFixtureGroups(
  services: GoogleService[],
): GoogleToolGroup[] {
  return googleGroupCatalog
    .filter((group) => services.includes(group.service))
    .map((group) => group.group);
}
export function googleFixtureScopes(services: GoogleService[]): string[] {
  return googleScopesForGroups(
    googleFixtureGroups(services),
    googleGroupCatalog,
  );
}

/** Static canonical catalog fixture for component and hook tests. */
export const googleGroupCatalog = [
  {
    group: "gmail_read",
    service: "gmail",
    operations: [
      "gmail_search_messages",
      "gmail_get_message",
      "gmail_batch_get_messages",
      "gmail_search_threads",
      "gmail_get_thread",
      "gmail_download_attachment",
    ],
    request_scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
  },
  {
    group: "gmail_labels",
    service: "gmail",
    operations: [
      "gmail_list_labels",
      "gmail_get_label",
      "gmail_create_label",
      "gmail_update_label",
      "gmail_delete_label",
    ],
    request_scopes: ["https://www.googleapis.com/auth/gmail.labels"],
  },
  {
    group: "gmail_drafts",
    service: "gmail",
    operations: [
      "gmail_list_drafts",
      "gmail_get_draft",
      "gmail_create_draft",
      "gmail_update_draft",
      "gmail_delete_draft",
    ],
    request_scopes: [
      "https://www.googleapis.com/auth/gmail.compose",
      "https://www.googleapis.com/auth/gmail.readonly",
    ],
  },
  {
    group: "gmail_send",
    service: "gmail",
    operations: [
      "gmail_send_draft",
      "gmail_send_message",
      "gmail_reply_message",
      "gmail_forward_message",
    ],
    request_scopes: [
      "https://www.googleapis.com/auth/gmail.readonly",
      "https://www.googleapis.com/auth/gmail.compose",
    ],
  },
  {
    group: "gmail_organize",
    service: "gmail",
    operations: [
      "gmail_modify_message",
      "gmail_batch_modify_messages",
      "gmail_modify_thread",
      "gmail_trash_message",
      "gmail_untrash_message",
      "gmail_trash_thread",
      "gmail_untrash_thread",
    ],
    request_scopes: ["https://www.googleapis.com/auth/gmail.modify"],
  },
  {
    group: "gmail_filters",
    service: "gmail",
    operations: [
      "gmail_list_filters",
      "gmail_get_filter",
      "gmail_create_filter",
      "gmail_delete_filter",
      "gmail_replace_filter",
      "gmail_apply_filter",
      "gmail_preview_filter",
    ],
    request_scopes: [
      "https://www.googleapis.com/auth/gmail.settings.basic",
      "https://www.googleapis.com/auth/gmail.modify",
    ],
  },
  {
    group: "calendar_read",
    service: "calendar",
    operations: [
      "calendar_list_calendars",
      "calendar_list_events",
      "calendar_get_event",
      "calendar_list_instances",
    ],
    request_scopes: [
      "https://www.googleapis.com/auth/calendar.events.readonly",
      "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    ],
  },
  {
    group: "calendar_availability",
    service: "calendar",
    operations: ["calendar_query_freebusy", "calendar_suggest_time"],
    request_scopes: [
      "https://www.googleapis.com/auth/calendar.events.freebusy",
    ],
  },
  {
    group: "calendar_events",
    service: "calendar",
    operations: [
      "calendar_create_event",
      "calendar_update_event",
      "calendar_delete_event",
      "calendar_respond_event",
    ],
    request_scopes: ["https://www.googleapis.com/auth/calendar.events"],
  },
  {
    group: "calendar_status",
    service: "calendar",
    operations: [
      "calendar_list_status_events",
      "calendar_create_status_event",
      "calendar_update_status_event",
      "calendar_delete_status_event",
    ],
    request_scopes: ["https://www.googleapis.com/auth/calendar.events"],
  },
  {
    group: "calendar_create",
    service: "calendar",
    operations: ["calendar_create_calendar"],
    request_scopes: ["https://www.googleapis.com/auth/calendar.app.created"],
  },
  {
    group: "drive_read",
    service: "drive",
    operations: [
      "drive_search_files",
      "drive_get_metadata",
      "drive_read_content",
      "drive_download_file",
      "drive_export_file",
      "drive_get_link",
    ],
    request_scopes: ["https://www.googleapis.com/auth/drive.readonly"],
  },
  {
    group: "drive_files",
    service: "drive",
    operations: [
      "drive_create_file",
      "drive_create_folder",
      "drive_copy_file",
      "drive_update_metadata",
      "drive_update_content",
      "drive_append_text",
      "drive_import_document",
      "drive_import_spreadsheet",
      "drive_import_presentation",
    ],
    request_scopes: ["https://www.googleapis.com/auth/drive.file"],
  },
  {
    group: "drive_sharing",
    service: "drive",
    operations: [
      "drive_list_permissions",
      "drive_get_permission",
      "drive_create_permission",
      "drive_update_permission",
      "drive_delete_permission",
      "drive_update_access",
    ],
    request_scopes: ["https://www.googleapis.com/auth/drive.file"],
  },
  {
    group: "drive_ownership",
    service: "drive",
    operations: ["drive_transfer_ownership"],
    request_scopes: ["https://www.googleapis.com/auth/drive.file"],
  },
] satisfies GoogleGroupDefinition[];
