import { useTranslations } from "next-intl";
import { useState } from "react";
import { AgentRuntimeEnvironmentVariables } from "./AgentRuntimeEnvironmentVariables";
import type {
  RuntimeEnvironmentEditorStatus,
  RuntimeEnvironmentVariableDraft,
} from "@/shared/runtime-environment/types";

export const storedEntries: RuntimeEnvironmentVariableDraft[] = [
  {
    id: "sample-1",
    name: "OPENAI_API_KEY",
    value: "",
    hasStoredValue: true,
    nameError: null,
    valueError: null,
  },
  {
    id: "sample-2",
    name: "NOTION_TOKEN",
    value: "",
    hasStoredValue: true,
    nameError: null,
    valueError: null,
  },
  {
    id: "sample-3",
    name: "DEPLOY_ENV",
    value: "",
    hasStoredValue: true,
    nameError: null,
    valueError: null,
  },
];

export const editingEntries: RuntimeEnvironmentVariableDraft[] = [
  ...storedEntries.slice(0, 2),
  {
    id: "sample-new",
    name: "SENTRY_AUTH_TOKEN",
    value: "storybook-demo-not-a-real-token",
    hasStoredValue: false,
    nameError: null,
    valueError: null,
  },
];

/** In-memory Storybook harness. It never calls product persistence or injection APIs. */
export function RuntimeEnvironmentPreview({
  initialEntries = storedEntries,
  initiallyDirty = false,
}: {
  initialEntries?: RuntimeEnvironmentVariableDraft[];
  initiallyDirty?: boolean;
}): React.ReactElement {
  const t = useTranslations(
    "workspace.agents.runtimeSettings.environmentVariables",
  );
  const [savedEntries, setSavedEntries] = useState(
    initialEntries.filter((entry) => entry.hasStoredValue),
  );
  const [entries, setEntries] = useState(initialEntries);
  const [status, setStatus] = useState<RuntimeEnvironmentEditorStatus>({
    type: initiallyDirty ? "DIRTY" : "UNCHANGED",
  });
  const [nextId, setNextId] = useState(1);

  const validate = (
    draft: RuntimeEnvironmentVariableDraft[],
  ): RuntimeEnvironmentVariableDraft[] =>
    draft.map((entry) => ({
      ...entry,
      nameError: !/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(entry.name)
        ? t("invalidName")
        : draft.filter((other) => other.name === entry.name).length > 1
          ? t("duplicateName")
          : null,
      valueError:
        !entry.hasStoredValue && entry.value.length === 0
          ? t("requiredValue")
          : null,
    }));

  const update = (draft: RuntimeEnvironmentVariableDraft[]): void => {
    setEntries(validate(draft));
    setStatus({ type: "DIRTY" });
  };

  return (
    <AgentRuntimeEnvironmentVariables
      state={{ type: "READY", entries, canManage: true, status }}
      onAdd={() => {
        update([
          ...entries,
          {
            id: `preview-${nextId}`,
            name: "",
            value: "",
            hasStoredValue: false,
            nameError: null,
            valueError: null,
          },
        ]);
        setNextId(nextId + 1);
      }}
      onNameChange={(id, name) =>
        update(
          entries.map((entry) =>
            entry.id === id ? { ...entry, name } : entry,
          ),
        )
      }
      onValueChange={(id, value) =>
        update(
          entries.map((entry) =>
            entry.id === id ? { ...entry, value } : entry,
          ),
        )
      }
      onRemove={(id) => update(entries.filter((entry) => entry.id !== id))}
      onDiscard={() => {
        setEntries(savedEntries);
        setStatus({ type: "UNCHANGED" });
      }}
      onSave={() => {
        const validated = validate(entries);
        setEntries(validated);
        if (validated.some((entry) => entry.nameError || entry.valueError)) {
          return;
        }
        const saved = entries.map((entry) => ({
          ...entry,
          value: "",
          hasStoredValue: true,
        }));
        setSavedEntries(saved);
        setEntries(saved);
        setStatus({ type: "SAVED" });
      }}
      onRetry={() => {}}
    />
  );
}
