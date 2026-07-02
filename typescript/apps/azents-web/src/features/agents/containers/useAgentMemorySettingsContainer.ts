"use client";

/** Agent Memory settings container. */

import { useState } from "react";
import { trpc } from "@/trpc/client";
import type { AgentResponse, MemoryResponse } from "@azents/public-client";

export type MemoryScopeValue = "agent" | "user";

export interface MemoryDraft {
  type: string;
  name: string;
  description: string;
  content: string;
}

type DraftState =
  | { type: "create"; draft: MemoryDraft }
  | { type: "edit"; memoryId: string; draft: MemoryDraft }
  | null;

export type MemoryListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; memories: MemoryResponse[] };

export interface AgentMemorySettingsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentMemorySettingsContainerOutput {
  handle: string;
  agent: AgentResponse;
  memoryEnabled: boolean;
  scope: MemoryScopeValue;
  query: string;
  listState: MemoryListState;
  draftState: DraftState;
  actionError: string | null;
  saving: boolean;
  deletingId: string | null;
  togglingMemory: boolean;
  onScopeChange: (scope: MemoryScopeValue) => void;
  onQueryChange: (query: string) => void;
  onMemoryEnabledChange: (enabled: boolean) => void;
  onStartCreate: () => void;
  onStartEdit: (memory: MemoryResponse) => void;
  onCancelDraft: () => void;
  onDraftChange: (draft: MemoryDraft) => void;
  onSaveDraft: () => void;
  onDeleteMemory: (memory: MemoryResponse) => void;
}

const EMPTY_DRAFT: MemoryDraft = {
  type: "project",
  name: "",
  description: "",
  content: "",
};

function toDraft(memory: MemoryResponse): MemoryDraft {
  return {
    type: memory.type,
    name: memory.name,
    description: memory.description,
    content: memory.content,
  };
}

function normalizeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown error";
}

export function useAgentMemorySettingsContainer({
  handle,
  agent,
}: AgentMemorySettingsContainerProps): AgentMemorySettingsContainerOutput {
  const utils = trpc.useUtils();
  const [scope, setScope] = useState<MemoryScopeValue>("agent");
  const [query, setQuery] = useState("");
  const [draftState, setDraftState] = useState<DraftState>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(agent.memory_enabled);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const listQuery = trpc.agent.listMemories.useQuery({
    handle,
    agentId: agent.id,
    scope,
    type: null,
    query: query.trim() === "" ? null : query.trim(),
  });

  const createMutation = trpc.agent.createMemory.useMutation({
    onSuccess: () => {
      setDraftState(null);
      setActionError(null);
      void utils.agent.listMemories.invalidate();
    },
    onError: (error) => setActionError(normalizeError(error)),
  });

  const updateMutation = trpc.agent.updateMemory.useMutation({
    onSuccess: () => {
      setDraftState(null);
      setActionError(null);
      void utils.agent.listMemories.invalidate();
    },
    onError: (error) => setActionError(normalizeError(error)),
  });

  const deleteMutation = trpc.agent.deleteMemory.useMutation({
    onMutate: (input) => setDeletingId(input.memoryId),
    onSuccess: () => {
      setActionError(null);
      void utils.agent.listMemories.invalidate();
    },
    onError: (error) => setActionError(normalizeError(error)),
    onSettled: () => setDeletingId(null),
  });

  const toggleMutation = trpc.agent.update.useMutation({
    onSuccess: (updatedAgent) => {
      setMemoryEnabled(updatedAgent.memory_enabled);
      setActionError(null);
      void utils.agent.get.invalidate({ handle, agentId: agent.id });
      void utils.agent.list.invalidate({ handle });
    },
    onError: (error) => {
      setMemoryEnabled((current) => !current);
      setActionError(normalizeError(error));
    },
  });

  const listState: MemoryListState = listQuery.isLoading
    ? { type: "LOADING" }
    : listQuery.isError
      ? { type: "ERROR", message: normalizeError(listQuery.error) }
      : { type: "LOADED", memories: listQuery.data?.items ?? [] };

  return {
    handle,
    agent,
    memoryEnabled,
    scope,
    query,
    listState,
    draftState,
    actionError,
    saving: createMutation.isPending || updateMutation.isPending,
    deletingId,
    togglingMemory: toggleMutation.isPending,
    onScopeChange: (nextScope) => {
      setScope(nextScope);
      setDraftState(null);
      setActionError(null);
    },
    onQueryChange: setQuery,
    onMemoryEnabledChange: (enabled) => {
      setMemoryEnabled(enabled);
      toggleMutation.mutate({
        handle,
        agentId: agent.id,
        memory_enabled: enabled,
      });
    },
    onStartCreate: () => {
      setActionError(null);
      setDraftState({ type: "create", draft: { ...EMPTY_DRAFT } });
    },
    onStartEdit: (memory) => {
      setActionError(null);
      setDraftState({
        type: "edit",
        memoryId: memory.id,
        draft: toDraft(memory),
      });
    },
    onCancelDraft: () => setDraftState(null),
    onDraftChange: (draft) =>
      setDraftState((current) => {
        if (current === null) {
          return current;
        }
        return { ...current, draft };
      }),
    onSaveDraft: () => {
      if (draftState === null) {
        return;
      }
      if (draftState.type === "create") {
        createMutation.mutate({
          handle,
          agentId: agent.id,
          scope,
          ...draftState.draft,
        });
        return;
      }
      updateMutation.mutate({
        handle,
        agentId: agent.id,
        memoryId: draftState.memoryId,
        ...draftState.draft,
      });
    },
    onDeleteMemory: (memory) => {
      deleteMutation.mutate({
        handle,
        agentId: agent.id,
        memoryId: memory.id,
      });
    },
  };
}
