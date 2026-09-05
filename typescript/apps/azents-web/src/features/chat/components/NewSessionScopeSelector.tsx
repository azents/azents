"use client";

/** Scope selector for the first message of a new Agent session. */

import { SegmentedControl } from "@mantine/core";
import { useTranslations } from "next-intl";
import type { AgentDraftSessionScope } from "../containers/useAgentDraftChatContainer";

export interface NewSessionScopeSelectorProps {
  value: AgentDraftSessionScope;
  onChange: (scope: AgentDraftSessionScope) => void;
}

function parseSessionScope(value: string): AgentDraftSessionScope {
  return value === "user" ? "user" : "team";
}

export function NewSessionScopeSelector({
  value,
  onChange,
}: NewSessionScopeSelectorProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");

  return (
    <SegmentedControl
      size="xs"
      value={value}
      onChange={(nextValue) => onChange(parseSessionScope(nextValue))}
      data={[
        { label: t("sessions.teamTab"), value: "team" },
        { label: t("sessions.myTab"), value: "user" },
      ]}
      aria-label={t("sessions.newSessionScope")}
    />
  );
}
