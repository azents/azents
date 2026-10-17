"use client";

import { useState } from "react";
import { trpc } from "@/trpc/client";
import type { PersonalToolsState } from "../types";
import type { PersonalToolkitResponse } from "@azents/public-client";

export interface PersonalToolsProps {
  handle: string;
  state: PersonalToolsState;
  pending: boolean;
  error: boolean;
  deleteTarget: PersonalToolkitResponse | null;
  testResult: { success: boolean; message: string } | null;
  onReload: () => void;
  onDelete: (toolkit: PersonalToolkitResponse | null) => void;
  onConfirmDelete: () => void;
  onToggle: (toolkit: PersonalToolkitResponse, enabled: boolean) => void;
  onTest: (toolkit: PersonalToolkitResponse) => void;
}

export function usePersonalToolsContainer({
  handle,
}: {
  handle: string;
}): PersonalToolsProps {
  const utils = trpc.useUtils();
  const query = trpc.personalToolkit.list.useQuery(
    { handle },
    { retry: false },
  );
  const remove = trpc.personalToolkit.remove.useMutation();
  const update = trpc.personalToolkit.update.useMutation();
  const test = trpc.personalToolkit.testSavedConnection.useMutation();
  const [deleteTarget, setDeleteTarget] =
    useState<PersonalToolkitResponse | null>(null);
  const [error, setError] = useState(false);
  const [testResult, setTestResult] =
    useState<PersonalToolsProps["testResult"]>(null);
  const pending = remove.isPending || update.isPending || test.isPending;
  const state: PersonalToolsState = query.isError
    ? { type: "ERROR" }
    : query.data == null
      ? { type: "LOADING" }
      : { type: "READY", items: query.data.items };
  async function invalidate(): Promise<void> {
    await Promise.all([
      utils.personalToolkit.list.invalidate({ handle }),
      utils.personalToolkit.get.invalidate({ handle }),
      utils.personalToolkit.accessForAgent.invalidate({ handle }),
    ]);
  }
  async function confirmDelete(): Promise<void> {
    if (!deleteTarget || pending) {
      return;
    }
    setError(false);
    try {
      await remove.mutateAsync({ handle, toolkitId: deleteTarget.id });
    } catch {
      setError(true);
      return;
    }
    setDeleteTarget(null);
    await invalidate();
  }
  async function toggle(
    toolkit: PersonalToolkitResponse,
    enabled: boolean,
  ): Promise<void> {
    if (pending) {
      return;
    }
    setError(false);
    try {
      await update.mutateAsync({ handle, toolkitId: toolkit.id, enabled });
    } catch {
      setError(true);
      return;
    }
    await invalidate();
  }
  async function testConnection(
    toolkit: PersonalToolkitResponse,
  ): Promise<void> {
    if (pending) {
      return;
    }
    setError(false);
    setTestResult(null);
    try {
      const result = await test.mutateAsync({ handle, toolkitId: toolkit.id });
      setTestResult({ success: result.success, message: result.message });
    } catch {
      setError(true);
    }
  }
  return {
    handle,
    state,
    pending,
    error,
    deleteTarget,
    testResult,
    onReload: () => {
      void utils.personalToolkit.list.invalidate({ handle });
    },
    onDelete: (toolkit) => {
      if (!pending) {
        setDeleteTarget(toolkit);
        setError(false);
      }
    },
    onConfirmDelete: () => {
      void confirmDelete();
    },
    onToggle: (toolkit, enabled) => {
      void toggle(toolkit, enabled);
    },
    onTest: (toolkit) => {
      void testConnection(toolkit);
    },
  };
}
