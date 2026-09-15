import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentSettingsSectionPage } from "@/features/agents/AgentSettingsSectionPage";
import { trpc } from "@/trpc/server";
import type { AgentSettingsSection } from "@/features/agents/AgentSettingsSectionPage";

function parseSection(value: string): AgentSettingsSection | null {
  switch (value) {
    case "profile":
    case "model":
    case "capabilities":
    case "admins":
    case "subagents":
    case "memory":
    case "runtime":
    case "services":
    case "channels":
    case "projects":
    case "danger":
      return value;
    default:
      return null;
  }
}

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; agentId: string; section: string }>;
}): Promise<React.ReactElement> {
  const { handle, agentId, section: rawSection } = await params;
  const section = parseSection(rawSection);
  if (section === null) {
    notFound();
  }
  try {
    const agent = await trpc.agent.get({ handle, agentId });
    if (section === "services" && agent.runtime_capability !== "managed") {
      notFound();
    }
    return (
      <AgentSettingsSectionPage
        handle={handle}
        agent={agent}
        section={section}
      />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
