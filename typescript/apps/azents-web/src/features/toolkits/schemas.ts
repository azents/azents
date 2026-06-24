/** Toolkit form Zod schema */

import { z } from "zod/v4";
import { TOOLKIT_SLUG_REGEX } from "@/shared/lib/toolkit-slug";

export const shellConfigSchema = z.object({
  allowed_domains: z.array(z.string()).default([]),
  denied_domains: z.array(z.string()).default([]),
});

export type ShellConfigValues = z.infer<typeof shellConfigSchema>;

export const toolkitFormSchema = z.object({
  toolkitType: z.string().min(1),
  slug: z.string().min(1).max(100).regex(TOOLKIT_SLUG_REGEX),
  name: z.string().min(1).max(255),
  description: z.string().optional(),
  prompt: z.string().optional(),
  config: z.record(z.string(), z.unknown()),
  credentials: z.record(z.string(), z.unknown()).nullable().optional(),
  enabled: z.boolean(),
});

export type ToolkitFormValues = z.infer<typeof toolkitFormSchema>;
