import { z } from "zod/v4";

export const googleTaskSchema = z.enum([
  "calendar_read",
  "calendar_availability",
  "calendar_edit",
  "drive_read",
  "drive_files",
  "gmail_read",
  "gmail_drafts",
  "gmail_modify",
]);
export const googleScopeSchema = z.object({
  handle: z.string().min(1),
  agentId: z.string().min(1).optional(),
});
export const googleDesiredSchema = z
  .object({
    tasks: z.array(googleTaskSchema).min(1),
    timeout: z.number().positive().max(300),
  })
  .strict();
export const googleReconnectSettingsSchema = googleDesiredSchema
  .extend({
    security_risk_acknowledged: z.boolean(),
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
