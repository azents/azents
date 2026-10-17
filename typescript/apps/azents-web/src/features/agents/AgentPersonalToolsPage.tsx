"use client";

import { personalToolsSetupPath } from "@/features/personal-tools/navigation";
import { PersonalAccessPage } from "@/features/personal-tools/PersonalAccessPage";
import { AgentSettingsLayout } from "./components/AgentSettingsLayout";
import type { AgentResponse } from "@azents/public-client";

export function AgentPersonalToolsPage({
  handle,
  agent,
  originSessionId,
}: {
  handle: string;
  agent: AgentResponse;
  originSessionId?: string;
}): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={handle}
      agent={agent}
      backTarget="agent"
      originSessionId={originSessionId}
    >
      <PersonalAccessPage
        key={`${handle}:${agent.id}`}
        type="agent"
        handle={handle}
        agentId={agent.id}
        agentName={agent.name}
        originSessionId={originSessionId}
        setupHref={personalToolsSetupPath({
          handle,
          agentId: agent.id,
          sessionId: originSessionId,
        })}
      />
    </AgentSettingsLayout>
  );
}
