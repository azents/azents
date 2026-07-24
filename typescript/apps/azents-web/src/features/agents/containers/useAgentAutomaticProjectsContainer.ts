"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAgentWorkspaceDirectoryPickerContainer } from "@/features/agent-workspace/containers/useAgentWorkspaceDirectoryPickerContainer";
import { trpc } from "@/trpc/client";
import {
  type AutomaticProjectRow,
  type AutomaticProjectsBaseline,
  automaticProjectsErrorProjection,
  type AutomaticProjectsState,
  commitAutomaticProjectsReplacement,
  dedupeProjectPaths,
  deriveAutomaticProjectsState,
  fetchLatestAutomaticProjects,
  initializeAutomaticProjectsBaseline,
  normalizeProjectPath,
  projectBasename,
  type ProjectPreviewStatus,
} from "../automaticProjects";
import type { ProjectDirectoryPickerEntry } from "@/features/agent-workspace/types";
import type { ApiErrorProjection } from "@/trpc/api-error";
import type { AgentResponse } from "@azents/public-client";

interface AgentAutomaticProjectsContainerProps {
  handle: string;
  agent: AgentResponse;
}

export interface AgentAutomaticProjectsContainerOutput {
  handle: string;
  agent: AgentResponse;
  state: AutomaticProjectsState;
  projectPaths: string[];
  isProjectPickerOpen: boolean;
  pickerState: ReturnType<
    typeof useAgentWorkspaceDirectoryPickerContainer
  >["state"];
  onAddProject: () => void;
  onCloseProjectPicker: () => void;
  onOpenProjectPickerDirectory: (path: string) => void;
  onSelectProjectPickerDirectory: (entry: ProjectDirectoryPickerEntry) => void;
  onRefreshProjectPicker: () => void;
  onStartRuntimeForProjectPicker: () => void;
  onRemoveProject: (path: string) => void;
  onMoveProject: (path: string, direction: "up" | "down") => void;
  onSave: () => Promise<void>;
  onRetrySave: () => Promise<void>;
  onReloadLatest: () => Promise<void>;
}

function genericError(error: unknown): string {
  return error instanceof Error ? error.message : "Request failed.";
}

function statusForPath(
  path: string,
  previewEntries: ReadonlyMap<
    string,
    { value: ProjectPreviewStatus; detail: string | null }
  >,
  hasPreview: boolean,
): { value: ProjectPreviewStatus; detail: string | null } {
  const preview = previewEntries.get(path);
  if (preview) {
    return preview;
  }
  return hasPreview
    ? { value: "missing", detail: null }
    : { value: "unchecked", detail: null };
}

export function useAgentAutomaticProjectsContainer({
  handle,
  agent,
}: AgentAutomaticProjectsContainerProps): AgentAutomaticProjectsContainerOutput {
  const utils = trpc.useUtils();
  const policyQuery = trpc.agent.getAutomaticSessionProjects.useQuery({
    handle,
    agentId: agent.id,
  });
  const [draftPaths, setDraftPaths] = useState<string[]>([]);
  const [draftInitialized, setDraftInitialized] = useState(false);
  const [baseline, setBaseline] = useState<AutomaticProjectsBaseline | null>(
    null,
  );
  const [saveError, setSaveError] = useState<ApiErrorProjection | null>(null);
  const policyMutation =
    trpc.agent.replaceAutomaticSessionProjects.useMutation();
  const previewQuery = trpc.chat.previewProjectBrowserManifest.useQuery(
    { agentId: agent.id, projectPaths: draftPaths },
    { enabled: draftPaths.length > 0 },
  );
  const normalizedDraftPaths = useMemo(
    () => dedupeProjectPaths(draftPaths),
    [draftPaths],
  );

  useEffect(() => {
    if (!policyQuery.data) {
      return;
    }
    const initialized = initializeAutomaticProjectsBaseline(
      baseline,
      policyQuery.data,
    );
    if (initialized === baseline) {
      return;
    }
    setBaseline(initialized);
    setDraftPaths(initialized.paths);
    setDraftInitialized(true);
  }, [baseline, policyQuery.data]);

  useEffect(() => {
    setDraftInitialized(false);
    setBaseline(null);
    setDraftPaths([]);
    setSaveError(null);
  }, [agent.id, handle]);

  const previewEntries = useMemo(() => {
    const entries = new Map<
      string,
      { value: ProjectPreviewStatus; detail: string | null }
    >();
    for (const entry of previewQuery.data?.entries ?? []) {
      entries.set(entry.path, {
        value: entry.status.value,
        detail: entry.status.detail ?? null,
      });
    }
    return entries;
  }, [previewQuery.data?.entries]);

  const rows = useMemo<AutomaticProjectRow[]>(
    () =>
      normalizedDraftPaths.map((path) => {
        const preview = statusForPath(
          path,
          previewEntries,
          previewQuery.data != null,
        );
        return {
          path,
          name: projectBasename(path),
          status: preview.value,
          detail: preview.detail,
        };
      }),
    [normalizedDraftPaths, previewEntries, previewQuery.data],
  );
  const dirty =
    baseline !== null &&
    JSON.stringify(baseline.paths) !== JSON.stringify(normalizedDraftPaths);

  const onSelectProjectPickerDirectory = useCallback(
    (entry: ProjectDirectoryPickerEntry): void => {
      if (entry.kind !== "directory") {
        return;
      }
      setDraftPaths((previous) =>
        dedupeProjectPaths([...previous, normalizeProjectPath(entry.path)]),
      );
      setSaveError(null);
    },
    [],
  );
  const picker = useAgentWorkspaceDirectoryPickerContainer({
    handle,
    agentId: agent.id,
    onSelectDirectory: onSelectProjectPickerDirectory,
  });
  const onStartRuntimeForProjectPicker = useCallback((): void => {
    setSaveError(null);
    picker.startRuntime();
  }, [picker]);

  const onRemoveProject = useCallback((path: string): void => {
    setDraftPaths((previous) =>
      previous.filter(
        (candidate) =>
          normalizeProjectPath(candidate) !== normalizeProjectPath(path),
      ),
    );
    setSaveError(null);
  }, []);
  const onMoveProject = useCallback(
    (path: string, direction: "up" | "down"): void => {
      setDraftPaths((previous) => {
        const index = previous.indexOf(path);
        const nextIndex = direction === "up" ? index - 1 : index + 1;
        if (index < 0 || nextIndex < 0 || nextIndex >= previous.length) {
          return previous;
        }
        const next = [...previous];
        const [item] = next.splice(index, 1);
        if (!item) {
          return previous;
        }
        next.splice(nextIndex, 0, item);
        return next;
      });
      setSaveError(null);
    },
    [],
  );

  const onSave = useCallback(async (): Promise<void> => {
    if (baseline === null || policyMutation.isPending || !dirty) {
      return;
    }
    setSaveError(null);
    try {
      const saved = await commitAutomaticProjectsReplacement({
        mutate: () =>
          policyMutation.mutateAsync({
            handle,
            agentId: agent.id,
            expectedRevision: baseline.revision,
            projectPaths: normalizedDraftPaths,
          }),
        setPolicyData: (response) =>
          utils.agent.getAutomaticSessionProjects.setData(
            { handle, agentId: agent.id },
            response,
          ),
        invalidatePolicy: () =>
          utils.agent.getAutomaticSessionProjects.invalidate({
            handle,
            agentId: agent.id,
          }),
        invalidatePreview: () =>
          utils.chat.previewProjectBrowserManifest.invalidate({
            agentId: agent.id,
          }),
      });
      setBaseline(saved);
      setDraftPaths(saved.paths);
      setSaveError(null);
    } catch (error) {
      const projection = automaticProjectsErrorProjection(error);
      if (projection) {
        setSaveError(projection);
      } else {
        setSaveError({
          code: null,
          message: genericError(error),
          path: null,
        });
      }
    }
  }, [
    agent.id,
    baseline,
    dirty,
    handle,
    normalizedDraftPaths,
    policyMutation,
    utils.agent.getAutomaticSessionProjects,
    utils.chat.previewProjectBrowserManifest,
  ]);

  const onReloadLatest = useCallback(async (): Promise<void> => {
    setSaveError(null);
    const latest = await fetchLatestAutomaticProjects({
      invalidatePolicy: () =>
        utils.agent.getAutomaticSessionProjects.invalidate({
          handle,
          agentId: agent.id,
        }),
      fetchPolicy: () =>
        utils.agent.getAutomaticSessionProjects.fetch({
          handle,
          agentId: agent.id,
        }),
    });
    setBaseline(latest);
    setDraftPaths(latest.paths);
    setDraftInitialized(true);
  }, [agent.id, handle, utils.agent.getAutomaticSessionProjects]);

  const state = useMemo<AutomaticProjectsState>(() => {
    return deriveAutomaticProjectsState({
      policyLoading: policyQuery.isLoading,
      policyLoaded: baseline !== null,
      policyError:
        baseline === null && policyQuery.isError
          ? genericError(policyQuery.error)
          : null,
      draftInitialized,
      mutationPending: policyMutation.isPending,
      revision: baseline?.revision ?? 0,
      rows,
      updatedAt: baseline?.updatedAt ?? "",
      dirty,
      saveError,
    });
  }, [
    baseline,
    dirty,
    draftInitialized,
    policyMutation.isPending,
    policyQuery.error,
    policyQuery.isError,
    policyQuery.isLoading,
    rows,
    saveError,
  ]);

  return {
    handle,
    agent,
    state,
    projectPaths: normalizedDraftPaths,
    isProjectPickerOpen: picker.isOpen,
    pickerState: picker.state,
    onAddProject: picker.open,
    onCloseProjectPicker: picker.close,
    onOpenProjectPickerDirectory: picker.openDirectory,
    onSelectProjectPickerDirectory: picker.selectDirectory,
    onRefreshProjectPicker: picker.refresh,
    onStartRuntimeForProjectPicker,
    onRemoveProject,
    onMoveProject,
    onSave,
    onRetrySave: onSave,
    onReloadLatest,
  };
}
