"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  RuntimeEnvironmentVariableDraft,
  RuntimeEnvironmentVariablesProps,
  RuntimeEnvironmentVariablesState,
} from "../runtime-environment-types";
import type { RuntimeEnvironmentEntryEditWritable } from "@azents/public-client";

export interface AgentRuntimeEnvironmentVariablesContainerProps {
  handle: string;
  agentId: string;
}

export function useAgentRuntimeEnvironmentVariablesContainer({
  handle,
  agentId,
}: AgentRuntimeEnvironmentVariablesContainerProps): RuntimeEnvironmentVariablesProps {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  const utils = trpc.useUtils();
  const input = { handle, agentId };
  const query = trpc.agent.getRuntimeEnvironment.useQuery(input);
  const [draft, setDraft] = useState<RuntimeEnvironmentVariableDraft[] | null>(
    null,
  );
  const [saved, setSaved] = useState(false);
  const mutation = trpc.agent.replaceRuntimeEnvironment.useMutation({
    onSuccess: async (settings) => {
      utils.agent.getRuntimeEnvironment.setData(input, settings);
      setDraft(null);
      setSaved(true);
      await utils.agent.getRuntimeEnvironment.invalidate(input);
      await utils.workspace.getAgentEnvironmentSelection.invalidate(input);
    },
  });

  const storedEntries: RuntimeEnvironmentVariableDraft[] = (
    query.data?.entries ?? []
  ).map((entry) => ({
    id: entry.name,
    name: entry.name,
    value: "",
    hasStoredValue: entry.has_value,
    nameError: null,
    valueError: null,
  }));
  const entries = draft ?? storedEntries;
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
        !entry.hasStoredValue && entry.value.length === 0
          ? t("requiredValue")
          : null,
    }));
  const update = (rows: RuntimeEnvironmentVariableDraft[]): void => {
    setDraft(validate(rows));
    setSaved(false);
    mutation.reset();
  };
  const dirty =
    draft !== null &&
    (entries.length !== storedEntries.length ||
      entries.some((entry, index) => {
        const stored = storedEntries[index];
        return (
          !stored ||
          entry.name !== stored.name ||
          entry.id !== stored.id ||
          entry.value.length > 0
        );
      }));
  const state: RuntimeEnvironmentVariablesState = query.isError
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
              : dirty
                ? { type: "DIRTY" }
                : saved
                  ? { type: "SAVED" }
                  : { type: "UNCHANGED" },
        };

  return {
    state,
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
      if (query.data?.can_manage !== true || mutation.isPending || !dirty) {
        return;
      }
      const validated = validate(entries);
      setDraft(validated);
      if (validated.some((entry) => entry.nameError || entry.valueError)) {
        return;
      }
      const edits: RuntimeEnvironmentEntryEditWritable[] = validated.map(
        (entry) => ({
          name: entry.name,
          value:
            entry.hasStoredValue && entry.value.length === 0
              ? { type: "stored", name: entry.id }
              : { type: "replace", value: entry.value },
        }),
      );
      mutation.mutate({ ...input, entries: edits });
    },
    onRetry: () => {
      void utils.agent.getRuntimeEnvironment.invalidate(input);
    },
  };
}
