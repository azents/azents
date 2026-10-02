"use client";

/** Agent Memory settings container. */

import { useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  AgentResponse,
  HistoricalMemoryResponse,
  MemoryResponse,
} from "@azents/public-client";

export type MemoryKindValue = "saved" | "historical";
export type SavedMemoryScopeValue = "agent" | "user";
export type HistoricalMemoryScopeValue = "team" | "user";

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

export type SavedMemoryListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; memories: MemoryResponse[] };

export type HistoricalMemoryListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      memories: HistoricalMemoryResponse[];
      hasMore: boolean;
    };

export interface AgentMemorySettingsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentMemorySettingsContainerOutput {
  handle: string;
  agent: AgentResponse;
  memoryEnabled: boolean;
  kind: MemoryKindValue;
  savedScope: SavedMemoryScopeValue;
  historicalScope: HistoricalMemoryScopeValue;
  savedQuery: string;
  historicalQuery: string;
  savedListState: SavedMemoryListState;
  historicalListState: HistoricalMemoryListState;
  draftState: DraftState;
  actionError: string | null;
  saving: boolean;
  deletingId: string | null;
  togglingMemory: boolean;
  loadingMoreHistorical: boolean;
  onKindChange: (kind: MemoryKindValue) => void;
  onSavedScopeChange: (scope: SavedMemoryScopeValue) => void;
  onHistoricalScopeChange: (scope: HistoricalMemoryScopeValue) => void;
  onSavedQueryChange: (query: string) => void;
  onHistoricalQueryChange: (query: string) => void;
  onLoadMoreHistorical: () => void;
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
  const [kind, setKind] = useState<MemoryKindValue>("saved");
  const [savedScope, setSavedScope] = useState<SavedMemoryScopeValue>("agent");
  const [historicalScope, setHistoricalScope] =
    useState<HistoricalMemoryScopeValue>("team");
  const [savedQuery, setSavedQuery] = useState("");
  const [historicalQuery, setHistoricalQuery] = useState("");
  const [draftState, setDraftState] = useState<DraftState>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(agent.memory_enabled);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const savedListQuery = trpc.agent.listMemories.useQuery(
    {
      handle,
      agentId: agent.id,
      scope: savedScope,
      type: null,
      query: savedQuery.trim() === "" ? null : savedQuery.trim(),
    },
    { enabled: kind === "saved" },
  );

  const historicalListQuery =
    trpc.agent.listHistoricalMemories.useInfiniteQuery(
      {
        handle,
        agentId: agent.id,
        scope: historicalScope,
        query: historicalQuery.trim() === "" ? null : historicalQuery.trim(),
        limit: 20,
      },
      {
        enabled: kind === "historical",
        getNextPageParam: (lastPage) => lastPage.next_cursor,
      },
    );

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

  const savedListState: SavedMemoryListState = savedListQuery.isLoading
    ? { type: "LOADING" }
    : savedListQuery.isError
      ? { type: "ERROR", message: normalizeError(savedListQuery.error) }
      : { type: "LOADED", memories: savedListQuery.data?.items ?? [] };

  const historicalListState: HistoricalMemoryListState =
    historicalListQuery.isLoading
      ? { type: "LOADING" }
      : historicalListQuery.isError
        ? {
            type: "ERROR",
            message: normalizeError(historicalListQuery.error),
          }
        : {
            type: "LOADED",
            memories:
              historicalListQuery.data?.pages.flatMap((page) => page.items) ??
              [],
            hasMore: historicalListQuery.hasNextPage,
          };

  return {
    handle,
    agent,
    memoryEnabled,
    kind,
    savedScope,
    historicalScope,
    savedQuery,
    historicalQuery,
    savedListState,
    historicalListState,
    draftState,
    actionError,
    saving: createMutation.isPending || updateMutation.isPending,
    deletingId,
    togglingMemory: toggleMutation.isPending,
    loadingMoreHistorical: historicalListQuery.isFetchingNextPage,
    onKindChange: (nextKind) => {
      setKind(nextKind);
      setDraftState(null);
      setActionError(null);
    },
    onSavedScopeChange: (nextScope) => {
      setSavedScope(nextScope);
      setDraftState(null);
      setActionError(null);
    },
    onHistoricalScopeChange: setHistoricalScope,
    onSavedQueryChange: setSavedQuery,
    onHistoricalQueryChange: setHistoricalQuery,
    onLoadMoreHistorical: () => {
      void historicalListQuery.fetchNextPage();
    },
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
          scope: savedScope,
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
