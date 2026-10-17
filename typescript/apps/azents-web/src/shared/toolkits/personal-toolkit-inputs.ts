import { z } from "zod/v4";
import { normalizeExplicitToolkitSlug } from "../lib/toolkit-identifiers.ts";

const id = z.string().min(1);
export const personalToolkitScopeInput = z.object({ handle: id }).strict();
const slug = z.string().refine((value) => {
  const normalized = normalizeExplicitToolkitSlug(value);
  return normalized == null || typeof normalized === "string";
});
const mode = z.enum(["all", "selected"]);
const fields = {
  slug: slug.optional(),
  name: z.string().max(255).optional(),
  description: z.string().nullable().optional(),
  prompt: z.string().nullable().optional(),
  config: z.record(z.string(), z.unknown()).optional(),
  credentials: z.record(z.string(), z.unknown()).optional(),
  enabled: z.boolean().optional(),
  alwaysExposeTools: z.boolean().optional(),
};

/** Account ownership is derived by the public API, never accepted from a form. */
export const personalToolkitCreateInput = z
  .object({
    handle: id,
    ...fields,
    toolkitType: z.string().min(1).max(100),
    config: z.record(z.string(), z.unknown()),
  })
  .strict();
export const personalToolkitSavedInput = z
  .object({ handle: id, toolkitId: id })
  .strict();
export const personalToolkitUpdateInput = z
  .object({ handle: id, toolkitId: id, ...fields })
  .strict();
export const personalToolkitAgentInput = z
  .object({ handle: id, agentId: id })
  .strict();
const accessFields = {
  expected_mode: mode,
  mode: mode.nullable(),
  allow_agent_ids: z.array(id),
  restrict_agent_ids: z.array(id),
};
export const personalToolkitAccessInput = z
  .object({ handle: id, toolkitId: id, ...accessFields })
  .strict();
export const personalToolkitAgentAccessInput = personalToolkitAgentInput.extend(
  {
    mutations: z.array(z.object({ toolkit_id: id, ...accessFields }).strict()),
  },
);
export const personalToolkitTestInput = z
  .object({
    handle: id,
    toolkitType: z.string().min(1).max(100),
    toolkitConfigId: id.nullable(),
    config: z.record(z.string(), z.unknown()),
    credentials: z.record(z.string(), z.unknown()).nullable(),
  })
  .strict();
export const personalToolkitExchangeInput = personalToolkitSavedInput.extend({
  code: z.string().min(1).max(8192),
  state: z.string().min(1).max(16384),
});
