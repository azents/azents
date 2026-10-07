"use client";

/** Agent Memory settings container. */

import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  ConsolidatedMemoryState,
  DraftState,
  HistoricalMemoryListState,
  HistoricalMemoryScopeValue,
  HistoricalMemoryView,
  MemoryDraft,
  MemoryKindValue,
  MemoryPaginationState,
  SavedMemoryListState,
  SavedMemoryScopeValue,
} from "../types";
import type { AgentResponse, MemoryResponse } from "@azents/public-client";
import type { RefCallback } from "react";

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
  historicalView: HistoricalMemoryView;
  consolidatedState: ConsolidatedMemoryState;
  paginationState: MemoryPaginationState;
  scrollRootRef: RefCallback<HTMLDivElement>;
  scrollEndRef: RefCallback<HTMLDivElement>;
  onHistoricalViewChange: (view: HistoricalMemoryView) => void;
  onRetryNextPage: () => void;
  onKindChange: (kind: MemoryKindValue) => void;
  onSavedScopeChange: (scope: SavedMemoryScopeValue) => void;
  onHistoricalScopeChange: (scope: HistoricalMemoryScopeValue) => void;
  onSavedQueryChange: (query: string) => void;
  onHistoricalQueryChange: (query: string) => void;
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

/** Observe the active list inside its real scrolling container. */
export function useMemoryScrollPagination({
  enabled,
  pageKey,
  listKey,
  onNextPage,
}: {
  enabled: boolean;
  pageKey: string;
  listKey: string;
  onNextPage: () => void;
}): {
  scrollRootRef: RefCallback<HTMLDivElement>;
  scrollEndRef: RefCallback<HTMLDivElement>;
} {
  const [root, setRoot] = useState<HTMLDivElement | null>(null);
  const [end, setEnd] = useState<HTMLDivElement | null>(null);
  const nextPage = useRef(onNextPage);
  useEffect(() => {
    if (root !== null) {
      root.scrollTop = 0;
    }
  }, [root, listKey]);
  useEffect(() => {
    nextPage.current = onNextPage;
  }, [onNextPage]);
  useEffect(() => {
    if (!enabled || root === null || end === null) {
      return;
    }
    let requested = false;
    const observer = new IntersectionObserver(
      (entries) => {
        if (!requested && entries.some((entry) => entry.isIntersecting)) {
          requested = true;
          nextPage.current();
        }
      },
      { root },
    );
    observer.observe(end);
    return () => observer.disconnect();
  }, [enabled, root, end, pageKey]);
  return { scrollRootRef: setRoot, scrollEndRef: setEnd };
}

export function useAgentMemorySettingsContainer({
  handle,
  agent,
}: AgentMemorySettingsContainerProps): AgentMemorySettingsContainerOutput {
  const t = useTranslations("workspace.agents.memorySettings");
  const utils = trpc.useUtils();
  const [kind, setKind] = useState<MemoryKindValue>("saved");
  const [savedScope, setSavedScope] = useState<SavedMemoryScopeValue>("agent");
  const [historicalScope, setHistoricalScope] =
    useState<HistoricalMemoryScopeValue>("team");
  const [savedQuery, setSavedQuery] = useState("");
  const [historicalQuery, setHistoricalQuery] = useState("");
  const [historicalView, setHistoricalView] =
    useState<HistoricalMemoryView>("overview");
  const [draftState, setDraftState] = useState<DraftState>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(agent.memory_enabled);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const savedListQuery = trpc.agent.listMemories.useInfiniteQuery(
    {
      handle,
      agentId: agent.id,
      scope: savedScope,
      type: null,
      query: savedQuery.trim() === "" ? null : savedQuery.trim(),
      limit: 20,
    },
    {
      enabled: kind === "saved",
      getNextPageParam: (lastPage) => lastPage.next_cursor,
    },
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
        enabled: kind === "historical" && historicalView === "sessions",
        getNextPageParam: (lastPage) => lastPage.next_cursor,
      },
    );

  const consolidatedQuery = trpc.agent.getConsolidatedMemory.useQuery(
    { handle, agentId: agent.id, scope: historicalScope },
    { enabled: kind === "historical" && historicalView === "overview" },
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
    onSuccess: (memory, input) => {
      setDraftState(null);
      setActionError(null);
      void utils.agent.listMemories.invalidate();
      void utils.agent.getMemory.invalidate({
        handle: input.handle,
        agentId: input.agentId,
        memoryId: memory.id,
      });
    },
    onError: (error) => setActionError(normalizeError(error)),
  });

  const deleteMutation = trpc.agent.deleteMemory.useMutation({
    onMutate: (input) => setDeletingId(input.memoryId),
    onSuccess: (_data, input) => {
      setActionError(null);
      void utils.agent.listMemories.invalidate();
      void utils.agent.getMemory.invalidate({
        handle: input.handle,
        agentId: input.agentId,
        memoryId: input.memoryId,
      });
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

  const savedData = savedListQuery.data ?? null;
  const historicalData = historicalListQuery.data ?? null;
  const savedListState: SavedMemoryListState = savedListQuery.isLoading
    ? { type: "LOADING" }
    : savedListQuery.isError && savedData === null
      ? { type: "ERROR", message: normalizeError(savedListQuery.error) }
      : {
          type: "LOADED",
          memories:
            savedListQuery.data?.pages.flatMap((page) => page.items) ?? [],
        };

  const historicalListState: HistoricalMemoryListState =
    historicalListQuery.isLoading
      ? { type: "LOADING" }
      : historicalListQuery.isError && historicalData === null
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

  const consolidatedState: ConsolidatedMemoryState = consolidatedQuery.isLoading
    ? { type: "LOADING" }
    : consolidatedQuery.isError
      ? { type: "ERROR", message: normalizeError(consolidatedQuery.error) }
      : {
          type: "LOADED",
          markdown: consolidatedQuery.data?.markdown ?? null,
          publishedAt: consolidatedQuery.data?.published_at ?? null,
        };
  const activeList = kind === "saved" ? savedListQuery : historicalListQuery;
  const paginationState: MemoryPaginationState = activeList.isFetchingNextPage
    ? { type: "LOADING" }
    : activeList.isFetchNextPageError
      ? { type: "ERROR", message: normalizeError(activeList.error) }
      : activeList.hasNextPage
        ? { type: "IDLE" }
        : { type: "END" };
  const fetchNextPage = useCallback((): void => {
    if (activeList.hasNextPage && !activeList.isFetching) {
      void activeList.fetchNextPage();
    }
  }, [activeList]);
  const scrollRefs = useMemoryScrollPagination({
    enabled:
      (kind === "saved" || historicalView === "sessions") &&
      activeList.hasNextPage &&
      !activeList.isFetching &&
      !activeList.isFetchNextPageError,
    listKey: `${kind}:${savedScope}:${historicalScope}:${savedQuery}:${historicalQuery}:${historicalView}`,
    pageKey: `${activeList.data?.pages.length ?? 0}`,
    onNextPage: fetchNextPage,
  });

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
    historicalView,
    consolidatedState,
    paginationState,
    ...scrollRefs,
    onHistoricalViewChange: setHistoricalView,
    onRetryNextPage: fetchNextPage,
    onKindChange: (nextKind) => {
      setKind(nextKind);
      setHistoricalView("overview");
      setDraftState(null);
      setActionError(null);
    },
    onSavedScopeChange: (nextScope) => {
      setSavedScope(nextScope);
      setDraftState(null);
      setActionError(null);
    },
    onHistoricalScopeChange: (scope) => {
      setHistoricalScope(scope);
      setHistoricalView("overview");
    },
    onSavedQueryChange: setSavedQuery,
    onHistoricalQueryChange: setHistoricalQuery,
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
      if (!window.confirm(t("deleteConfirm", { name: memory.name }))) {
        return;
      }
      deleteMutation.mutate({
        handle,
        agentId: agent.id,
        memoryId: memory.id,
      });
    },
  };
}
