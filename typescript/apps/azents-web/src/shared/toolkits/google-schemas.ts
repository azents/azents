import { z } from "zod/v4";

export const googleServiceSchema = z.enum(["calendar", "drive", "gmail"]);
export const googleToolGroupSchema = z.enum([
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
]);
export const googleScopeSchema = z
  .object({
    handle: z.string().min(1),
    agentId: z.string().min(1).optional(),
  })
  .strict();
export const googleReconnectSettingsSchema = z
  .object({
    services: z.array(googleServiceSchema),
    tool_groups: z.array(googleToolGroupSchema),
    oauth_request_scopes: z.array(z.string().min(1)),
    timeout: z.number().positive().max(300),
  })
  .strict();
export const googleDesiredSchema = googleReconnectSettingsSchema
  .extend({
    services: z.array(googleServiceSchema).min(1),
    tool_groups: z.array(googleToolGroupSchema).min(1),
  })
  .strict();
export const googleFinalSettingsSchema = googleReconnectSettingsSchema
  .extend({
    name: z.string().max(255).nullable(),
    slug: z.string().nullable(),
    description: z.string().nullable(),
    prompt: z.string().nullable(),
    enabled: z.boolean(),
    always_expose_tools: z.boolean(),
  })
  .strict();
