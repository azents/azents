"use client";

/**
 * Sentry tool settings form fields.
 *
 * Sentry MCP server URL and auth type are fixed on server (predefined),
 * so they are not exposed to user.
 */

import {
  Accordion,
  Button,
  Checkbox,
  NumberInput,
  Stack,
  Text,
} from "@mantine/core";
import { IconPlugConnected, IconSettings } from "@tabler/icons-react";
import { useCallback, useMemo } from "react";
import { getArray, isOneOf } from "@/shared/lib/unknown-value";
import { ProviderConnectionTestFeedback } from "./ProviderConnectionTestFeedback";

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

const SKILL_VALUES = ["inspect", "seer", "docs", "triage", "manage"] as const;

type SentrySkill = (typeof SKILL_VALUES)[number];

function isSentrySkill(value: unknown): value is SentrySkill {
  return isOneOf(value, SKILL_VALUES);
}

import type { SimpleProviderFieldsProps } from "../types";

export function SentryConfigFields({
  config,
  onConfigChange,
  toolkitConfigId,
  testState,
  onTestConnection,
}: SimpleProviderFieldsProps): React.ReactElement {
  const timeoutValue = typeof config.timeout === "number" ? config.timeout : 30;
  const enabledSkills = useMemo(
    () =>
      Array.isArray(config.enabled_skills)
        ? getArray(config.enabled_skills, isSentrySkill)
        : ["inspect", "seer"],
    [config.enabled_skills],
  );

  // Connection test

  const handleSkillToggle = useCallback(
    (skill: SentrySkill, checked: boolean): void => {
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
            onClick={onTestConnection}
            loading={testState.type === "TESTING"}
            disabled={testState.type === "TESTING"}
          >
            Connection test
          </Button>

          <ProviderConnectionTestFeedback state={testState} preWrap={false} />
        </Stack>
      )}
    </Stack>
  );
}
