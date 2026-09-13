import { z } from "zod/v4";

const agentTypeEnum = z.enum(["public", "private"]);

const builtinToolConfigSchema = z
  .object({
    name: z.string().min(1),
    config: z.record(z.string(), z.unknown()).optional().default({}),
  })
  .strict();

const selectableModelSettingsInputSchema = z
  .object({
    context_window_tokens: z.number().int().positive().nullable().optional(),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    builtin_tools: z.array(builtinToolConfigSchema).nullable().optional(),
  })
  .strict();

const selectableModelCandidateInputSchema = z
  .object({
    model_selection: z
      .object({
        llm_provider_integration_id: z.string().min(1),
        model_identifier: z.string().min(1),
      })
      .strict(),
    settings: selectableModelSettingsInputSchema.nullable().optional(),
  })
  .strict();

const selectableModelOptionInputSchema = z
  .object({
    label: z.string().min(1),
    candidates: z.array(selectableModelCandidateInputSchema).min(1).max(5),
    subagent_enabled: z.boolean().optional(),
    subagent_guidance: z.string().max(500).nullable().optional(),
  })
  .strict();

const subagentSettingsSchema = z
  .object({
    max_subagents: z.number().int().min(0),
    max_depth: z.number().int().min(0),
  })
  .strict();

const modelParametersSchema = z
  .object({
    temperature: z.number().min(0).max(2).nullable().optional(),
    context_window_tokens: z.number().int().positive().nullable().optional(),
    max_output_tokens: z.number().int().positive().nullable().optional(),
    top_p: z.number().min(0).max(1).nullable().optional(),
    top_k: z.number().int().positive().nullable().optional(),
    stop_sequences: z.array(z.string()).max(4).nullable().optional(),
    reasoning_effort: z
      .enum(["none", "minimal", "low", "medium", "high", "xhigh", "max"])
      .nullable()
      .optional(),
    builtin_tools: z.array(builtinToolConfigSchema).optional(),
  })
  .strict()
  .nullable();

export const agentCreateInputSchema = z
  .object({
    handle: z.string().min(1),
    name: z.string().min(1).max(100),
    description: z.string().optional(),
    selectable_model_options: z
      .array(selectableModelOptionInputSchema)
      .optional(),
    main_model_label: z.string().nullable().optional(),
    lightweight_model_label: z.string().nullable().optional(),
    model_parameters: modelParametersSchema.optional(),
    system_prompt: z.string().optional(),
    enabled: z.boolean().optional(),
    type: agentTypeEnum.optional(),
    runtime_profile_id: z.string().min(1).nullable().optional(),
    terminal_enabled: z.boolean().optional(),
    memory_enabled: z.boolean().optional(),
    tool_search_enabled: z.boolean().optional(),
    max_turns: z.number().int().positive().nullable().optional(),
    auto_archive_ttl_days: z.number().int().positive().optional(),
    subagent_settings: subagentSettingsSchema.optional(),
  })
  .strict();

export const agentUpdateInputSchema = z
  .object({
    handle: z.string().min(1),
    agentId: z.string().min(1),
    name: z.string().min(1).max(100).optional(),
    description: z.string().nullable().optional(),
    selectable_model_options: z
      .array(selectableModelOptionInputSchema)
      .optional(),
    main_model_label: z.string().nullable().optional(),
    lightweight_model_label: z.string().nullable().optional(),
    model_parameters: modelParametersSchema.optional(),
    system_prompt: z.string().nullable().optional(),
    enabled: z.boolean().optional(),
    type: agentTypeEnum.optional(),
    runtime_profile_id: z.string().min(1).nullable().optional(),
    expected_runtime_profile_selection_version: z
      .number()
      .int()
      .positive()
      .optional(),
    terminal_enabled: z.boolean().optional(),
    memory_enabled: z.boolean().optional(),
    tool_search_enabled: z.boolean().optional(),
    max_turns: z.number().int().positive().nullable().optional(),
    auto_archive_ttl_days: z.number().int().positive().optional(),
    subagent_settings: subagentSettingsSchema.optional(),
  })
  .strict();

export const workspaceModelSettingsUpdateInputSchema = z
  .object({
    handle: z.string().min(1),
    default_selectable_model_options: z
      .array(selectableModelOptionInputSchema)
      .optional(),
    default_main_model_label: z.string().nullable().optional(),
    default_lightweight_model_label: z.string().nullable().optional(),
  })
  .strict();
