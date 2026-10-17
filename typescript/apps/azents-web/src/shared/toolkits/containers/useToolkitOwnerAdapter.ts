"use client";

import { skipToken } from "@tanstack/react-query";
import { trimToolkitWhitespace } from "@/shared/lib/toolkit-identifiers";
import { trpc } from "@/trpc/client";
import { metadataProviderFields } from "../toolkit-form-lifecycle";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitOwnerScope } from "../toolkit-owner-scope";
import type { ToolkitConfigFormState } from "../types";

export interface ToolkitSavedMetadata {
  id: string;
  name: string;
  slug: string;
}
export interface ToolkitOwnerAdapter {
  state: ToolkitConfigFormState;
  saving: boolean;
  connecting: boolean;
  disconnecting: boolean;
  save: (
    values: ToolkitFormValues,
    credentials: Record<string, unknown> | null,
  ) => Promise<ToolkitSavedMetadata>;
  connect: () => Promise<string>;
  disconnect: () => Promise<void>;
  invalidate: () => Promise<void>;
}

/** Bind common form operations to the actual owner without a synthetic Workspace. */
export function useToolkitOwnerAdapter(
  scope: ToolkitOwnerScope,
  toolkitId: string | null,
): ToolkitOwnerAdapter {
  const utils = trpc.useUtils();
  const shared = trpc.toolkit.getConfig.useQuery(
    !("owner" in scope) && scope.agentId == null && toolkitId != null
      ? { handle: scope.handle, toolkitId }
      : skipToken,
  );
  const agent = trpc.toolkit.getAgentConfig.useQuery(
    !("owner" in scope) && scope.agentId != null && toolkitId != null
      ? {
          handle: scope.handle,
          agentId: scope.agentId,
          toolkitConfigId: toolkitId,
        }
      : skipToken,
  );
  const personal = trpc.personalToolkit.get.useQuery(
    "owner" in scope && toolkitId != null
      ? { handle: scope.handle, toolkitId }
      : skipToken,
  );
  const query =
    "owner" in scope ? personal : scope.agentId == null ? shared : agent;
  const state: ToolkitConfigFormState =
    toolkitId == null
      ? { type: "CREATE" }
      : query.isLoading
        ? { type: "LOADING" }
        : query.isError || query.data == null
          ? { type: "NOT_FOUND" }
          : { type: "EDIT", config: query.data };
  const createShared = trpc.toolkit.createConfig.useMutation();
  const updateShared = trpc.toolkit.updateConfig.useMutation();
  const createAgent = trpc.toolkit.createAgentConfig.useMutation();
  const updateAgent = trpc.toolkit.updateAgentConfig.useMutation();
  const createPersonal = trpc.personalToolkit.create.useMutation();
  const updatePersonal = trpc.personalToolkit.update.useMutation();
  const connectShared = trpc.toolkit.connectOauth.useMutation();
  const connectAgent = trpc.toolkit.connectAgentOauth.useMutation();
  const connectPersonal = trpc.personalToolkit.connectOauth.useMutation();
  const disconnectShared = trpc.toolkit.disconnectOauth.useMutation();
  const disconnectAgent = trpc.toolkit.disconnectAgentOauth.useMutation();
  const disconnectPersonal = trpc.personalToolkit.disconnectOauth.useMutation();

  async function invalidate(): Promise<void> {
    if ("owner" in scope) {
      await Promise.allSettled([
        utils.personalToolkit.list.invalidate({ handle: scope.handle }),
        utils.personalToolkit.accessForAgent.invalidate({
          handle: scope.handle,
        }),
        utils.personalToolkit.get.invalidate(
          toolkitId == null
            ? { handle: scope.handle }
            : { handle: scope.handle, toolkitId },
        ),
      ]);
    } else if (scope.agentId != null) {
      await Promise.allSettled([
        utils.toolkit.listAgentManagement.invalidate({
          handle: scope.handle,
          agentId: scope.agentId,
        }),
        toolkitId == null
          ? Promise.resolve()
          : utils.toolkit.getAgentConfig.invalidate({
              handle: scope.handle,
              agentId: scope.agentId,
              toolkitConfigId: toolkitId,
            }),
      ]);
      // A failed follow-up read cannot undo an acknowledged save or resurrect a draft.
      await utils.toolkit.listAgentManagement
        .fetch({ handle: scope.handle, agentId: scope.agentId })
        .catch(() => null);
    } else {
      await Promise.allSettled([
        utils.toolkit.listConfigs.invalidate({ handle: scope.handle }),
        toolkitId == null
          ? Promise.resolve()
          : utils.toolkit.getConfig.invalidate({
              handle: scope.handle,
              toolkitId,
            }),
      ]);
    }
  }
  async function save(
    values: ToolkitFormValues,
    credentials: Record<string, unknown> | null,
  ): Promise<ToolkitSavedMetadata> {
    if (toolkitId != null) {
      const edits = {
        slug: values.slug,
        name: values.name,
        description: values.description ?? null,
        prompt: values.prompt ?? null,
        ...metadataProviderFields(values.toolkitType, values.config),
        ...(credentials != null && { credentials }),
        enabled: values.enabled,
        alwaysExposeTools: values.alwaysExposeTools,
      };
      if ("owner" in scope) {
        return await updatePersonal.mutateAsync({
          handle: scope.handle,
          toolkitId,
          ...edits,
        });
      }
      if (scope.agentId != null) {
        return await updateAgent.mutateAsync({
          handle: scope.handle,
          agentId: scope.agentId,
          toolkitConfigId: toolkitId,
          ...edits,
        });
      }
      return await updateShared.mutateAsync({
        handle: scope.handle,
        toolkitId,
        ...edits,
      });
    }
    const creation = {
      toolkitType: values.toolkitType,
      ...(trimToolkitWhitespace(values.slug) && { slug: values.slug }),
      ...(trimToolkitWhitespace(values.name) && { name: values.name }),
      description: values.description,
      prompt: values.prompt,
      config: values.config,
      ...(credentials != null && { credentials }),
      enabled: values.enabled,
      alwaysExposeTools: values.alwaysExposeTools,
    };
    if ("owner" in scope) {
      return await createPersonal.mutateAsync({
        ...creation,
        handle: scope.handle,
      });
    }
    if (scope.agentId != null) {
      return await createAgent.mutateAsync({
        handle: scope.handle,
        agentId: scope.agentId,
        ...creation,
      });
    }
    return await createShared.mutateAsync({
      handle: scope.handle,
      ...creation,
    });
  }
  async function connect(): Promise<string> {
    if (toolkitId == null) {
      throw new Error("Save this Toolkit before starting OAuth.");
    }
    if ("owner" in scope) {
      return (
        await connectPersonal.mutateAsync({ handle: scope.handle, toolkitId })
      ).authorization_url;
    }
    if (scope.agentId != null) {
      return (
        await connectAgent.mutateAsync({
          handle: scope.handle,
          agentId: scope.agentId,
          toolkitConfigId: toolkitId,
        })
      ).authorization_url;
    }
    return (
      await connectShared.mutateAsync({
        handle: scope.handle,
        toolkitConfigId: toolkitId,
      })
    ).authorization_url;
  }
  async function disconnect(): Promise<void> {
    if (toolkitId == null) {
      throw new Error("Save this Toolkit before disconnecting OAuth.");
    }
    if ("owner" in scope) {
      await disconnectPersonal.mutateAsync({ handle: scope.handle, toolkitId });
    } else if (scope.agentId != null) {
      await disconnectAgent.mutateAsync({
        handle: scope.handle,
        agentId: scope.agentId,
        toolkitConfigId: toolkitId,
      });
    } else {
      await disconnectShared.mutateAsync({
        handle: scope.handle,
        toolkitConfigId: toolkitId,
      });
    }
    await invalidate();
  }
  return {
    state,
    save,
    connect,
    disconnect,
    invalidate,
    saving:
      createShared.isPending ||
      updateShared.isPending ||
      createAgent.isPending ||
      updateAgent.isPending ||
      createPersonal.isPending ||
      updatePersonal.isPending,
    connecting:
      connectShared.isPending ||
      connectAgent.isPending ||
      connectPersonal.isPending,
    disconnecting:
      disconnectShared.isPending ||
      disconnectAgent.isPending ||
      disconnectPersonal.isPending,
  };
}
