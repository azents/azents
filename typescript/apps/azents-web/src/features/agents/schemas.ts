/** Agent form Zod schema */

import { z } from "zod/v4";

/** Agent form schema. Agent directly selects model catalog selection snapshot. */
export const agentFormSchema = z.object({
  name: z.string().min(1).max(100),
  description: z.string().optional(),
  model_provider_integration_id: z.string().nullable(),
  model_selection_value: z.string().nullable(),
  lightweight_model_provider_integration_id: z.string().nullable(),
  lightweight_model_selection_value: z.string().nullable(),
  system_prompt: z.string().optional(),
  type: z.enum(["public", "private"]),
  enabled: z.boolean(),
  reasoning_effort: z.enum(["low", "medium", "high"]).nullable().optional(),
  context_window_tokens: z.number().int().positive().nullable().optional(),
  max_output_tokens: z.number().int().positive().nullable().optional(),
  shell_enabled: z.boolean().optional(),
  memory_enabled: z.boolean().optional(),
  max_turns: z.number().int().positive().nullable().optional(),
  builtin_tools: z.array(z.string()).optional().default([]),
});

export type AgentFormValues = z.infer<typeof agentFormSchema>;
