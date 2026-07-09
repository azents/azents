/** Agent form Zod schema */

import { z } from "zod/v4";
import { MAX_SELECTABLE_MODEL_OPTIONS } from "./model-selection";
import type { ModelCapabilities } from "@azents/public-client";

const selectableModelOptionFormValueSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  model_provider_integration_id: z.string().nullable(),
  model_selection_value: z.string().nullable(),
  model_display_name: z.string().nullable(),
  model_identifier: z.string().nullable(),
  normalized_capabilities: z.custom<ModelCapabilities>().nullable(),
});

/** Agent form schema. Agent model selections reference labels from a bounded selectable model option list. */
export const agentFormSchema = z
  .object({
    name: z.string().min(1).max(100),
    description: z.string().optional(),
    selectable_model_options: z
      .array(selectableModelOptionFormValueSchema)
      .min(1, "Add at least one model option")
      .max(MAX_SELECTABLE_MODEL_OPTIONS, "Add at most 10 model options"),
    main_model_label: z.string().nullable(),
    lightweight_model_label: z.string().nullable(),
    system_prompt: z.string().optional(),
    type: z.enum(["public", "private"]),
    enabled: z.boolean(),
    reasoning_effort: z.enum(["low", "medium", "high"]).nullable().optional(),
    context_window_tokens: z.number().int().positive().nullable().optional(),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    shell_enabled: z.boolean().optional(),
    memory_enabled: z.boolean().optional(),
    max_turns: z.number().int().positive().nullable().optional(),
    subagent_max_subagents: z.number().int().min(0),
    subagent_max_depth: z.number().int().min(0),
    builtin_tools: z.array(z.string()).optional().default([]),
  })
  .superRefine((values, ctx) => {
    const labels = new Set<string>();
    for (const [index, option] of values.selectable_model_options.entries()) {
      const label = option.label.trim();
      if (label.length === 0) {
        ctx.addIssue({
          code: "custom",
          path: ["selectable_model_options", index, "label"],
          message: "Model option label is required",
        });
      }
      if (labels.has(label)) {
        ctx.addIssue({
          code: "custom",
          path: ["selectable_model_options", index, "label"],
          message: "Model option labels must be unique",
        });
      }
      labels.add(label);
      if (option.model_selection_value == null) {
        ctx.addIssue({
          code: "custom",
          path: ["selectable_model_options", index, "model_selection_value"],
          message: "Choose a model for this option",
        });
      }
    }
  });

export type AgentFormValues = z.infer<typeof agentFormSchema>;
