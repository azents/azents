import {
  agentV1ListAgents,
  personalToolkitOauthV1ConnectPersonalOauth,
  personalToolkitOauthV1DisconnectPersonalOauth,
  personalToolkitOauthV1ExchangePersonalOauth,
  personalToolkitOauthV1TestPersonalConnection,
  personalToolkitOauthV1TestSavedPersonalConnection,
  personalToolkitV1CreatePersonalToolkit,
  personalToolkitV1DeletePersonalToolkit,
  personalToolkitV1GetAgentPersonalToolkitAccess,
  personalToolkitV1GetPersonalToolkit,
  personalToolkitV1ListPersonalToolkitAgents,
  personalToolkitV1ListPersonalToolkits,
  personalToolkitV1SaveAgentPersonalToolkitAccess,
  personalToolkitV1SavePersonalToolkitAccess,
  personalToolkitV1UpdatePersonalToolkit,
} from "@azents/public-client";
import { normalizeCredentialEdits } from "@/shared/lib/redacted-credentials";
import {
  personalToolkitAccessInput,
  personalToolkitAgentAccessInput,
  personalToolkitAgentInput,
  personalToolkitCreateInput,
  personalToolkitExchangeInput,
  personalToolkitSavedInput,
  personalToolkitScopeInput,
  personalToolkitTestInput,
  personalToolkitUpdateInput,
} from "@/shared/toolkits/personal-toolkit-inputs";
import { mapExpectedError } from "../api-error";
import { publicProcedure, router } from "../init";

async function request<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw mapExpectedError(error, {
      400: "BAD_REQUEST",
      401: "UNAUTHORIZED",
      403: "FORBIDDEN",
      404: "NOT_FOUND",
      409: "CONFLICT",
      422: "BAD_REQUEST",
    });
  }
}

/** Personal adapters require a real Workspace; authentication determines the User. */
export const personalToolkitRouter = router({
  list: publicProcedure
    .input(personalToolkitScopeInput)
    .query(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitV1ListPersonalToolkits({
          client: ctx.apiClient,
          path: { handle: input.handle },
          throwOnError: true,
        }),
      );
      return data;
    }),
  eligibleAgents: publicProcedure
    .input(personalToolkitScopeInput)
    .query(async ({ ctx, input }) => {
      const [eligible, profiles] = await request(() =>
        Promise.all([
          personalToolkitV1ListPersonalToolkitAgents({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          }),
          agentV1ListAgents({
            client: ctx.apiClient,
            path: { handle: input.handle },
            throwOnError: true,
          }),
        ]),
      );
      const byId = new Map(
        profiles.data.items.map((agent) => [agent.id, agent]),
      );
      return {
        items: eligible.data.items.map((agent) => ({
          ...agent,
          avatar: byId.get(agent.agent_id)?.avatar ?? null,
          description: byId.get(agent.agent_id)?.description ?? null,
        })),
      };
    }),
  get: publicProcedure
    .input(personalToolkitSavedInput)
    .query(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitV1GetPersonalToolkit({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }),
  create: publicProcedure
    .input(personalToolkitCreateInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitV1CreatePersonalToolkit({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            toolkit_type: input.toolkitType,
            slug: input.slug,
            name: input.name,
            description: input.description ?? null,
            prompt: input.prompt ?? null,
            config: input.config,
            credentials: normalizeCredentialEdits(input.credentials ?? null),
            enabled: input.enabled ?? true,
            always_expose_tools: input.alwaysExposeTools ?? false,
          },
          throwOnError: true,
        }),
      );
      return data;
    }),
  update: publicProcedure
    .input(personalToolkitUpdateInput)
    .mutation(async ({ ctx, input }) => {
      const credentials = normalizeCredentialEdits(input.credentials ?? null);
      const { data } = await request(() =>
        personalToolkitV1UpdatePersonalToolkit({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          body: {
            slug: input.slug,
            name: input.name,
            description: input.description,
            prompt: input.prompt,
            config: input.config,
            ...(credentials !== null && { credentials }),
            enabled: input.enabled,
            always_expose_tools: input.alwaysExposeTools,
          },
          throwOnError: true,
        }),
      );
      return data;
    }),
  remove: publicProcedure
    .input(personalToolkitSavedInput)
    .mutation(async ({ ctx, input }) => {
      await request(() =>
        personalToolkitV1DeletePersonalToolkit({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return null;
    }),
  accessForAgent: publicProcedure
    .input(personalToolkitAgentInput)
    .query(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitV1GetAgentPersonalToolkitAccess({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          throwOnError: true,
        }),
      );
      return data;
    }),
  saveAccess: publicProcedure
    .input(personalToolkitAccessInput)
    .mutation(async ({ ctx, input }) => {
      const { toolkitId, handle, ...body } = input;
      const { data } = await request(() =>
        personalToolkitV1SavePersonalToolkitAccess({
          client: ctx.apiClient,
          path: { handle, toolkit_id: toolkitId },
          body,
          throwOnError: true,
        }),
      );
      return data;
    }),
  saveAccessForAgent: publicProcedure
    .input(personalToolkitAgentAccessInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitV1SaveAgentPersonalToolkitAccess({
          client: ctx.apiClient,
          path: { handle: input.handle, agent_id: input.agentId },
          body: { mutations: input.mutations },
          throwOnError: true,
        }),
      );
      return data;
    }),
  testConnection: publicProcedure
    .input(personalToolkitTestInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitOauthV1TestPersonalConnection({
          client: ctx.apiClient,
          path: { handle: input.handle },
          body: {
            toolkit_type: input.toolkitType,
            toolkit_config_id: input.toolkitConfigId,
            config: input.config,
            credentials: normalizeCredentialEdits(input.credentials),
          },
          throwOnError: true,
        }),
      );
      return data;
    }),
  testSavedConnection: publicProcedure
    .input(personalToolkitSavedInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitOauthV1TestSavedPersonalConnection({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }),
  connectOauth: publicProcedure
    .input(personalToolkitSavedInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitOauthV1ConnectPersonalOauth({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return data;
    }),
  exchangeOauth: publicProcedure
    .input(personalToolkitExchangeInput)
    .mutation(async ({ ctx, input }) => {
      const { data } = await request(() =>
        personalToolkitOauthV1ExchangePersonalOauth({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          body: { code: input.code, state: input.state },
          throwOnError: true,
        }),
      );
      return data;
    }),
  disconnectOauth: publicProcedure
    .input(personalToolkitSavedInput)
    .mutation(async ({ ctx, input }) => {
      await request(() =>
        personalToolkitOauthV1DisconnectPersonalOauth({
          client: ctx.apiClient,
          path: { handle: input.handle, toolkit_id: input.toolkitId },
          throwOnError: true,
        }),
      );
      return null;
    }),
});
