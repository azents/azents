"use client";

/**
 * Sentry tool settings form fields.
 *
 * Sentry MCP server URL and auth type are fixed on server (predefined),
 * so they are not exposed to user.
 */

import {
  Accordion,
  Alert,
  Button,
  Checkbox,
  NumberInput,
  Stack,
  Text,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconCheck,
  IconPlugConnected,
  IconSettings,
} from "@tabler/icons-react";
import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";

/** Sentry skill group definition */
const SKILL_GROUPS = [
  {
    value: "inspect",
    label: "Issue/event lookup",
    description: "Sentry issue, event, trace lookup (read-only)",
  },
  {
    value: "seer",
    label: "AI analysis (Seer)",
    description: "AI-based root cause analysis and code fix suggestions",
  },
  {
    value: "docs",
    label: "SDK documentation",
    description: "Sentry SDK documentation lookup",
  },
  {
    value: "triage",
    label: "Issue management",
    description: "Change issue status (resolve, ignore, assign, etc.)",
  },
  {
    value: "manage",
    label: "Project/team management",
    description: "Create and manage projects, teams, DSNs",
  },
] as const;

type SentryConfig = Record<string, unknown>;
type SentryCredentials = Record<string, unknown> | null;

interface SentryConfigFieldsProps {
  config: SentryConfig;
  onConfigChange: (config: SentryConfig) => void;
  credentials: SentryCredentials;
  onCredentialsChange: (credentials: SentryCredentials) => void;
  /** Existing credentials existence in edit mode */
  hasCredentials: boolean;
  handle: string;
  /** Existing toolkit config ID in edit mode */
  toolkitConfigId?: string;
}

export function SentryConfigFields({
  config,
  onConfigChange,
  credentials,
  handle,
  toolkitConfigId,
}: SentryConfigFieldsProps): React.ReactElement {
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;
  const enabledSkills = useMemo(
    () =>
      Array.isArray(config.enabled_skills)
        ? (config.enabled_skills as string[])
        : ["inspect", "seer"],
    [config.enabled_skills],
  );

  // Connection test
  const testConnectionMutation = trpc.toolkit.testConnection.useMutation();

  const handleTestConnection = useCallback(() => {
    testConnectionMutation.mutate({
      handle,
      toolkitType: "sentry",
      toolkitConfigId: toolkitConfigId ?? null,
      config,
      credentials,
    });
  }, [handle, toolkitConfigId, config, credentials, testConnectionMutation]);

  const handleSkillToggle = useCallback(
    (skill: string, checked: boolean) => {
      const current = new Set(enabledSkills);
      if (checked) {
        current.add(skill);
      } else {
        current.delete(skill);
      }
      onConfigChange({ ...config, enabled_skills: [...current] });
    },
    [config, enabledSkills, onConfigChange],
  );

  return (
    <Stack gap="md">
      {/* Skill group selection */}
      <Stack gap="xs">
        <Text size="sm" fw={500}>
          Features to enable
        </Text>
        {SKILL_GROUPS.map((group) => (
          <Checkbox
            key={group.value}
            label={group.label}
            description={group.description}
            checked={enabledSkills.includes(group.value)}
            onChange={(e) =>
              handleSkillToggle(group.value, e.currentTarget.checked)
            }
          />
        ))}
      </Stack>

      {/* Advanced settings */}
      <Accordion variant="contained">
        <Accordion.Item value="advanced">
          <Accordion.Control icon={<IconSettings size={16} />}>
            Advanced settings
          </Accordion.Control>
          <Accordion.Panel>
            <NumberInput
              label="Timeout (seconds)"
              description="MCP request timeout. Default 30 seconds."
              value={timeoutValue}
              onChange={(v) => onConfigChange({ ...config, timeout: v })}
              min={1}
              max={300}
            />
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>

      {/* Connection test */}
      {toolkitConfigId && (
        <Stack gap="xs">
          <Button
            variant="light"
            leftSection={<IconPlugConnected size={16} />}
            onClick={handleTestConnection}
            loading={testConnectionMutation.isPending}
            disabled={testConnectionMutation.isPending}
          >
            Connection test
          </Button>

          {testConnectionMutation.isSuccess && (
            <Alert
              variant="light"
              color={testConnectionMutation.data.success ? "green" : "red"}
              icon={
                testConnectionMutation.data.success ? (
                  <IconCheck size={16} />
                ) : (
                  <IconAlertTriangle size={16} />
                )
              }
            >
              {testConnectionMutation.data.message}
            </Alert>
          )}
        </Stack>
      )}
    </Stack>
  );
}
