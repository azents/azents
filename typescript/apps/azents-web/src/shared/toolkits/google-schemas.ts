import { z } from "zod/v4";

export const googleServiceSchema = z.enum(["calendar", "drive", "gmail"]);
export const googleScopeSchema = z
  .object({
    handle: z.string().min(1),
    agentId: z.string().min(1).optional(),
  })
  .strict();
export const googleReconnectSettingsSchema = z
  .object({
    services: z.array(googleServiceSchema),
    oauth_request_scopes: z.array(z.string().min(1)),
    timeout: z.number().positive().max(300),
  })
  .strict();
export const googleDesiredSchema = googleReconnectSettingsSchema
  .extend({
    services: z.array(googleServiceSchema).min(1),
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
