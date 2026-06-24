"use client";

/**
 * EnvVarToolkit settings form fields.
 *
 * When workspace manager registers arbitrary environment variables (API key, etc.),
 * they are injected into child process settings when agent shell runs. Each entry
 * must follow POSIX variable name rules (^[a-zA-Z_][a-zA-Z0-9_]*$, both cases allowed),
 * and values are masked with PasswordInput.
 */

import {
  ActionIcon,
  Alert,
  Button,
  Checkbox,
  Group,
  PasswordInput,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { IconAlertTriangle, IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";

/** POSIX environment variable name regex (both cases allowed) */
const ENV_NAME_RE = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
const MAX_ENTRY_NAME_LEN = 64;
const MAX_ENTRY_VALUE_LEN = 4096;
const MAX_ENTRY_COUNT = 50;

interface EntryMeta {
  name: string;
  masked: boolean;
}

interface EnvVarConfig {
  entries: EntryMeta[];
}

interface EnvVarCredentials {
  values: Record<string, string>;
}

interface EnvVarConfigFieldsProps {
  config: Record<string, unknown>;
  onConfigChange: (config: Record<string, unknown>) => void;
  credentials: Record<string, unknown> | null;
  onCredentialsChange: (credentials: Record<string, unknown> | null) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
}

/** Parse config type-safely (guard unknown) */
function parseConfig(raw: Record<string, unknown>): EnvVarConfig {
  const entries = Array.isArray(raw.entries)
    ? (raw.entries as unknown[]).map((e) => {
        const entry = e as Record<string, unknown>;
        return {
          name: typeof entry.name === "string" ? entry.name : "",
          masked: typeof entry.masked === "boolean" ? entry.masked : true,
        };
      })
    : [];
  return { entries };
}

/** Parse credentials type-safely */
function parseCredentials(
  raw: Record<string, unknown> | null,
): EnvVarCredentials {
  if (raw == null) {
    return { values: {} };
  }
  const values =
    raw.values != null && typeof raw.values === "object"
      ? (raw.values as Record<string, unknown>)
      : {};
  const typedValues: Record<string, string> = {};
  for (const [key, val] of Object.entries(values)) {
    if (typeof val === "string") {
      typedValues[key] = val;
    }
  }
  return { values: typedValues };
}

export function EnvVarConfigFields({
  config,
  onConfigChange,
  credentials,
  onCredentialsChange,
  hasCredentials,
}: EnvVarConfigFieldsProps): React.ReactElement {
  const t = useTranslations("workspace.toolkits.envvar");

  const parsedConfig = useMemo(() => parseConfig(config), [config]);
  const parsedCreds = useMemo(
    () => parseCredentials(credentials),
    [credentials],
  );

  const [acknowledged, setAcknowledged] = useState(false);

  const updateEntry = useCallback(
    (index: number, patch: Partial<{ name: string; value: string }>) => {
      const newEntries = [...parsedConfig.entries];
      const newValues = { ...parsedCreds.values };
      const prev = newEntries[index];
      if (prev == null) {
        return;
      }

      const prevName = prev.name;
      const hasNewName = typeof patch.name === "string";
      const newName = hasNewName ? (patch.name as string) : prevName;

      if (hasNewName && patch.name !== prevName) {
        // Remap value key too when name changes
        if (prevName && prevName in newValues) {
          const prevValue = newValues[prevName];
          delete newValues[prevName];
          if (typeof prevValue === "string" && newName) {
            newValues[newName] = prevValue;
          }
        }
        newEntries[index] = { ...prev, name: patch.name as string };
      }

      if (typeof patch.value === "string" && newName) {
        newValues[newName] = patch.value;
      }

      onConfigChange({ ...config, entries: newEntries });
      onCredentialsChange({ values: newValues });
    },
    [
      parsedConfig.entries,
      parsedCreds.values,
      config,
      onConfigChange,
      onCredentialsChange,
    ],
  );

  const addEntry = useCallback(() => {
    if (parsedConfig.entries.length >= MAX_ENTRY_COUNT) {
      return;
    }
    const newEntries = [...parsedConfig.entries, { name: "", masked: true }];
    onConfigChange({ ...config, entries: newEntries });
  }, [parsedConfig.entries, config, onConfigChange]);

  const removeEntry = useCallback(
    (index: number) => {
      const target = parsedConfig.entries[index];
      if (target == null) {
        return;
      }

      const newEntries = parsedConfig.entries.filter((_, i) => i !== index);
      const newValues = { ...parsedCreds.values };
      if (target.name in newValues) {
        delete newValues[target.name];
      }
      onConfigChange({ ...config, entries: newEntries });
      onCredentialsChange({ values: newValues });
    },
    [
      parsedConfig.entries,
      parsedCreds.values,
      config,
      onConfigChange,
      onCredentialsChange,
    ],
  );

  const entryCount = parsedConfig.entries.length;
  const atLimit = entryCount >= MAX_ENTRY_COUNT;

  return (
    <Stack gap="md">
      <Alert
        variant="light"
        color="orange"
        icon={<IconAlertTriangle size={16} />}
        title={t("warningTitle")}
      >
        <Stack gap="xs">
          <Text size="sm">{t("warningBody")}</Text>
          <Checkbox
            checked={acknowledged}
            onChange={(e) => setAcknowledged(e.currentTarget.checked)}
            label={t("acknowledgeLabel")}
          />
        </Stack>
      </Alert>

      <Stack gap="xs">
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            {t("entriesLabel")}
          </Text>
          <Text size="xs" c="dimmed">
            {t("entriesCountLabel", {
              count: entryCount,
              max: MAX_ENTRY_COUNT,
            })}
          </Text>
        </Group>

        {entryCount === 0 && (
          <Text size="sm" c="dimmed">
            {t("emptyState")}
          </Text>
        )}

        {parsedConfig.entries.map((entry, index) => {
          const nameError =
            entry.name !== "" && !ENV_NAME_RE.test(entry.name)
              ? t("invalidNameError")
              : entry.name.length > MAX_ENTRY_NAME_LEN
                ? t("nameTooLongError", { max: MAX_ENTRY_NAME_LEN })
                : null;

          const inputValue = parsedCreds.values[entry.name] ?? "";
          const valueError =
            inputValue.length > MAX_ENTRY_VALUE_LEN
              ? t("valueTooLongError", { max: MAX_ENTRY_VALUE_LEN })
              : null;

          return (
            <Group key={index} gap="xs" align="flex-start" wrap="nowrap">
              <TextInput
                placeholder={t("namePlaceholder")}
                style={{ flex: 1 }}
                value={entry.name}
                onChange={(e) =>
                  updateEntry(index, { name: e.currentTarget.value })
                }
                error={nameError}
                maxLength={MAX_ENTRY_NAME_LEN}
              />
              <PasswordInput
                placeholder={
                  hasCredentials
                    ? t("valueEditPlaceholder")
                    : t("valuePlaceholder")
                }
                style={{ flex: 2 }}
                value={inputValue}
                onChange={(e) =>
                  updateEntry(index, { value: e.currentTarget.value })
                }
                error={valueError}
              />
              <ActionIcon
                variant="subtle"
                color="red"
                onClick={() => removeEntry(index)}
                aria-label={t("removeEntry")}
                mt={4}
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Group>
          );
        })}

        <Button
          variant="light"
          leftSection={<IconPlus size={14} />}
          onClick={addEntry}
          disabled={atLimit}
          size="xs"
          mt="xs"
        >
          {t("addEntry")}
        </Button>
        {atLimit && (
          <Text size="xs" c="dimmed">
            {t("entryLimitReached", { max: MAX_ENTRY_COUNT })}
          </Text>
        )}
      </Stack>
    </Stack>
  );
}
