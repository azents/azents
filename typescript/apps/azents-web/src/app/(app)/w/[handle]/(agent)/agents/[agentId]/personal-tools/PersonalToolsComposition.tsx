"use client";
import { AgentPersonalToolsPage } from "@/features/agents/AgentPersonalToolsPage";
import { personalToolsSetupPath } from "@/features/personal-tools/navigation";
import { PersonalAccessPage } from "@/features/personal-tools/PersonalAccessPage";
import type { AgentResponse } from "@azents/public-client";

export function PersonalToolsComposition({
  handle,
  agent,
  originSessionId,
}: {
  handle: string;
  agent: AgentResponse;
  originSessionId?: string;
}): React.ReactElement {
  return (
    <AgentPersonalToolsPage
      handle={handle}
      agent={agent}
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
    </AgentPersonalToolsPage>
  );
}
