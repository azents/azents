"use client";

import { AgentSettingsLayout } from "../../shared/agent-session/AgentSettingsLayout";
import type { AgentResponse } from "@azents/public-client";

export function AgentPersonalToolsPage({
  handle,
  agent,
  originSessionId,
  children,
}: {
  handle: string;
  agent: AgentResponse;
  originSessionId?: string;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <AgentSettingsLayout
      handle={handle}
      agent={agent}
      backTarget="agent"
      originSessionId={originSessionId}
    >
      {children}
    </AgentSettingsLayout>
  );
}
