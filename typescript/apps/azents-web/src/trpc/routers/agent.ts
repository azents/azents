/**
 * Agent tRPC router
 *
 * Per-workspace Agent CRUD + Admin management:
 * - list / get: Agent fetch (auth required, member or higher)
 * - create: Agent create (auth required, member or higher)
 * - update / remove: Agent update/delete (admin or owner)
 * - listAdmins / addAdmin / removeAdmin: Agent admin management
 */
import {
  agentV1AddAgentAdmin,
  agentV1CreateAgent,
  agentV1CreateAgentMemory,
  agentV1DeleteAgent,
  agentV1DeleteAgentMemory,
  agentV1FinalizeAvatar,
  agentV1GetAgent,
  agentV1GetAgentMemory,
  agentV1ListAgentAdmins,
  agentV1ListAgentMemories,
  agentV1ListAgents,
  agentV1RemoveAgentAdmin,
  agentV1RemoveAvatar,
  agentV1RequestAvatarUpload,
  agentV1UpdateAgent,
  agentV1UpdateAgentMemory,
} from "@azents/public-client";
import { z } from "zod/v4";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

const agentTypeEnum = z.enum(["public", "private"]);
const memoryScopeEnum = z.enum(["agent", "user"]);

const modelSelectionInputSchema = z
  .object({
    llm_provider_integration_id: z.string().min(1),
    model_identifier: z.string().min(1),
  })
  .nullable();

const builtinToolConfigSchema = z.object({
  name: z.string().min(1),
  config: z.record(z.string(), z.unknown()).optional().default({}),
});

const selectableModelSettingsInputSchema = z.object({
  context_window_tokens: z.number().int().positive().nullable().optional(),
  max_output_tokens: z.number().int().positive().nullable().optional(),
  builtin_tools: z.array(builtinToolConfigSchema).nullable().optional(),
  subagent_enabled: z.boolean().optional(),
  subagent_guidance: z.string().max(500).nullable().optional(),
});

const selectableModelOptionInputSchema = z.object({
  label: z.string().min(1),
  model_selection: z.object({
    llm_provider_integration_id: z.string().min(1),
    model_identifier: z.string().min(1),
  }),
  settings: selectableModelSettingsInputSchema.nullable().optional(),
});

const subagentSettingsSchema = z.object({
  max_subagents: z.number().int().min(0),
  max_depth: z.number().int().min(0),
});

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
  .nullable();

export const agentRouter = router({
  /** workspace of Agent list fetch */
  list: publicProcedure
    .input(z.object({ handle: z.string().min(1) }))
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1ListAgents({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
        });
      }
    }),

  /** Agent detail fetch */
  get: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1GetAgent({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Agent create */
  create: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        name: z.string().min(1).max(100),
        description: z.string().optional(),
        model_selection: modelSelectionInputSchema.optional(),
        lightweight_model_selection: modelSelectionInputSchema.optional(),
        selectable_model_options: z
          .array(selectableModelOptionInputSchema)
          .optional(),
        main_model_label: z.string().nullable().optional(),
        lightweight_model_label: z.string().nullable().optional(),
        model_parameters: modelParametersSchema.optional(),
        system_prompt: z.string().optional(),
        enabled: z.boolean().optional(),
        type: agentTypeEnum.optional(),
        shell_enabled: z.boolean().optional(),
        memory_enabled: z.boolean().optional(),
        tool_search_enabled: z.boolean().optional(),
        max_turns: z.number().int().positive().nullable().optional(),
        subagent_settings: subagentSettingsSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1CreateAgent({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            name: input.name,
            model_selection: input.model_selection ?? null,
            lightweight_model_selection:
              input.lightweight_model_selection ?? null,
            selectable_model_options: input.selectable_model_options,
            main_model_label: input.main_model_label,
            lightweight_model_label: input.lightweight_model_label,
            description: input.description ?? null,
            model_parameters: input.model_parameters ?? null,
            system_prompt: input.system_prompt ?? null,
            enabled: input.enabled ?? true,
            type: input.type ?? "public",
            shell_enabled: input.shell_enabled,
            memory_enabled: input.memory_enabled,
            tool_search_enabled: input.tool_search_enabled,
            max_turns: input.max_turns,
            subagent_settings: input.subagent_settings,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent update */
  update: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        name: z.string().min(1).max(100).optional(),
        description: z.string().nullable().optional(),
        model_selection: modelSelectionInputSchema.optional(),
        lightweight_model_selection: modelSelectionInputSchema.optional(),
        selectable_model_options: z
          .array(selectableModelOptionInputSchema)
          .optional(),
        main_model_label: z.string().nullable().optional(),
        lightweight_model_label: z.string().nullable().optional(),
        model_parameters: modelParametersSchema.optional(),
        system_prompt: z.string().nullable().optional(),
        enabled: z.boolean().optional(),
        type: agentTypeEnum.optional(),
        shell_enabled: z.boolean().optional(),
        memory_enabled: z.boolean().optional(),
        tool_search_enabled: z.boolean().optional(),
        max_turns: z.number().int().positive().nullable().optional(),
        subagent_settings: subagentSettingsSchema.optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1UpdateAgent({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            name: input.name,
            description: input.description,
            ...("model_selection" in input
              ? { model_selection: input.model_selection }
              : {}),
            ...("lightweight_model_selection" in input
              ? {
                  lightweight_model_selection:
                    input.lightweight_model_selection,
                }
              : {}),
            ...("selectable_model_options" in input
              ? { selectable_model_options: input.selectable_model_options }
              : {}),
            ...("main_model_label" in input
              ? { main_model_label: input.main_model_label }
              : {}),
            ...("lightweight_model_label" in input
              ? { lightweight_model_label: input.lightweight_model_label }
              : {}),
            model_parameters: input.model_parameters,
            system_prompt: input.system_prompt,
            enabled: input.enabled,
            type: input.type,
            shell_enabled: input.shell_enabled,
            memory_enabled: input.memory_enabled,
            tool_search_enabled: input.tool_search_enabled,
            max_turns: input.max_turns,
            subagent_settings: input.subagent_settings,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent delete */
  remove: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await agentV1DeleteAgent({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Agent admin list fetch */
  listAdmins: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1ListAgentAdmins({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Agent admin add */
  addAdmin: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        workspaceUserId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1AddAgentAdmin({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: { workspace_user_id: input.workspaceUserId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent memory list fetch */
  listMemories: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        scope: memoryScopeEnum,
        type: z.string().min(1).nullable().optional(),
        query: z.string().nullable().optional(),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1ListAgentMemories({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          query: {
            scope: input.scope,
            type: input.type ?? null,
            query: input.query ?? null,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent memory detail fetch */
  getMemory: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        memoryId: z.string().min(1),
      }),
    )
    .query(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1GetAgentMemory({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            memory_id: input.memoryId,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Agent memory create */
  createMemory: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        scope: memoryScopeEnum,
        type: z.string().min(1).max(50),
        name: z.string().min(1).max(255),
        description: z.string().min(1),
        content: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1CreateAgentMemory({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            scope: input.scope,
            type: input.type,
            name: input.name,
            description: input.description,
            content: input.content,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent memory update */
  updateMemory: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        memoryId: z.string().min(1),
        type: z.string().min(1).max(50).optional(),
        name: z.string().min(1).max(255).optional(),
        description: z.string().min(1).optional(),
        content: z.string().min(1).optional(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1UpdateAgentMemory({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            memory_id: input.memoryId,
          },
          body: {
            type: input.type,
            name: input.name,
            description: input.description,
            content: input.content,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
          422: "BAD_REQUEST",
        });
      }
    }),

  /** Agent memory delete */
  deleteMemory: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        memoryId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await agentV1DeleteAgentMemory({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            memory_id: input.memoryId,
          },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Avatar upload ticket (presigned PUT URL) issue */
  requestAvatarUpload: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        contentType: z.string().min(1),
        contentLength: z.number().int().positive(),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1RequestAvatarUpload({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            content_type: input.contentType,
            content_length: input.contentLength,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Avatar finalize (server-side verify + thumbnail publishing) */
  finalizeAvatar: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        uploadKey: z.string().min(1),
        filename: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1FinalizeAvatar({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: {
            upload_key: input.uploadKey,
            filename: input.filename,
          },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          400: "BAD_REQUEST",
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Avatar remove */
  removeAvatar: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { data } = await agentV1RemoveAvatar({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        });
        return data;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
        });
      }
    }),

  /** Agent admin remove */
  removeAdmin: publicProcedure
    .input(
      z.object({
        handle: z.string().min(1),
        agentId: z.string().min(1),
        adminWorkspaceUserId: z.string().min(1),
      }),
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await agentV1RemoveAgentAdmin({
          client: ctx.apiClient,
          path: {
            handle: input.handle,
            agent_id: input.agentId,
            admin_workspace_user_id: input.adminWorkspaceUserId,
          },
          throwOnError: true,
        });
        return null;
      } catch (e) {
        throw mapExpectedError(e, {
          401: "UNAUTHORIZED",
          403: "FORBIDDEN",
          404: "NOT_FOUND",
          409: "CONFLICT",
        });
      }
    }),
});
