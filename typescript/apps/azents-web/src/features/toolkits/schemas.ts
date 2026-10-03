/** Toolkit form Zod schema */

import { z } from "zod/v4";
import {
  normalizeExplicitToolkitSlug,
  trimToolkitWhitespace,
} from "@/shared/lib/toolkit-identifiers";
import { toolkitConfigWireSchema } from "./toolkit-config-projection";

export const shellConfigSchema = z.object({
  allowed_domains: z.array(z.string()).default([]),
  denied_domains: z.array(z.string()).default([]),
});

export type ShellConfigValues = z.infer<typeof shellConfigSchema>;

export const toolkitFormSchema = z
  .object({
    toolkitType: z.string().min(1),
    slug: z.string(),
    name: z.string().max(255),
    description: z.string().optional(),
    prompt: z.string().optional(),
    config: toolkitConfigWireSchema,
    credentials: z.record(z.string(), z.unknown()).nullable().optional(),
    enabled: z.boolean(),
    alwaysExposeTools: z.boolean(),
  })
  .superRefine((values, context) => {
    if (values.toolkitType === "mcp" && !trimToolkitWhitespace(values.name)) {
      context.addIssue({
        code: "custom",
        path: ["name"],
        message: "Name is required for generic MCP Toolkits.",
      });
    }
    const normalizedSlug = normalizeExplicitToolkitSlug(values.slug);
    if (normalizedSlug != null && typeof normalizedSlug !== "string") {
      context.addIssue({
        code: "custom",
        path: ["slug"],
        message: normalizedSlug.detail,
      });
    }
  });

export type ToolkitFormValues = z.infer<typeof toolkitFormSchema>;
