"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  RuntimeEnvironmentVariableDraft,
  RuntimeEnvironmentVariablesProps,
} from "@/features/agents/runtime-environment-types";
import type { WorkspaceEnvironmentEntryEditWritable } from "@azents/public-client";

export function useWorkspaceEnvironmentContainer({
  handle,
}: {
  handle: string;
}): RuntimeEnvironmentVariablesProps & { handle: string } {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  const utils = trpc.useUtils();
  const query = trpc.workspace.getEnvironment.useQuery({ handle });
  const [draft, setDraft] = useState<RuntimeEnvironmentVariableDraft[] | null>(
    null,
  );
  const [saved, setSaved] = useState(false);
  const mutation = trpc.workspace.replaceEnvironment.useMutation({
    onSuccess: async (settings) => {
      utils.workspace.getEnvironment.setData({ handle }, settings);
      setDraft(null);
      setSaved(true);
      await Promise.all([
        utils.workspace.getEnvironment.invalidate({ handle }),
        utils.workspace.getAgentEnvironmentSelection.invalidate(),
      ]);
    },
  });
  const stored = query.data?.entries ?? [];
  const entries =
    draft ??
    stored.map((entry) => ({
      id: entry.id,
      name: entry.name,
      value: "",
      hasStoredValue: entry.has_value,
      nameError: null,
      valueError: null,
    }));
  const validate = (
    rows: RuntimeEnvironmentVariableDraft[],
  ): RuntimeEnvironmentVariableDraft[] =>
    rows.map((entry) => ({
      ...entry,
      nameError:
        !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(entry.name) || entry.name.length > 64
          ? t("invalidName")
          : rows.filter((other) => other.name === entry.name).length > 1
            ? t("duplicateName")
            : null,
      valueError:
        !entry.hasStoredValue && !entry.value ? t("requiredValue") : null,
    }));
  const update = (rows: RuntimeEnvironmentVariableDraft[]): void => {
    setDraft(validate(rows));
    setSaved(false);
    mutation.reset();
  };
  return {
    handle,
    scope: "workspace",
    state: query.isError
      ? { type: "ERROR", message: query.error.message }
      : !query.data
        ? { type: "LOADING" }
        : {
            type: "READY",
            entries,
            canManage: query.data.can_manage,
            status: mutation.isPending
              ? { type: "SAVING" }
              : mutation.isError
                ? { type: "ERROR", message: mutation.error.message }
                : draft !== null
                  ? { type: "DIRTY" }
                  : saved
                    ? { type: "SAVED" }
                    : { type: "UNCHANGED" },
          },
    onAdd: () =>
      update([
        ...entries,
        {
          id: crypto.randomUUID(),
          name: "",
          value: "",
          hasStoredValue: false,
          nameError: null,
          valueError: null,
        },
      ]),
    onNameChange: (id, name) =>
      update(
        entries.map((entry) => (entry.id === id ? { ...entry, name } : entry)),
      ),
    onValueChange: (id, value) =>
      update(
        entries.map((entry) => (entry.id === id ? { ...entry, value } : entry)),
      ),
    onRemove: (id) => update(entries.filter((entry) => entry.id !== id)),
    onDiscard: () => {
      setDraft(null);
      setSaved(false);
      mutation.reset();
    },
    onSave: () => {
      if (query.data?.can_manage !== true || mutation.isPending) {
        return;
      }
      const rows = validate(entries);
      setDraft(rows);
      if (rows.some((entry) => entry.nameError || entry.valueError)) {
        return;
      }
      const edits: WorkspaceEnvironmentEntryEditWritable[] = rows.map(
        (entry) => {
          const original = stored.find((item) => item.id === entry.id);
          return {
            id: original?.id ?? null,
            name: entry.name,
            value:
              original && !entry.value
                ? { type: "stored", name: original.name }
                : { type: "replace", value: entry.value },
          };
        },
      );
      mutation.mutate({ handle, entries: edits });
    },
    onRetry: () => {
      void utils.workspace.getEnvironment.invalidate({ handle });
    },
  };
}
