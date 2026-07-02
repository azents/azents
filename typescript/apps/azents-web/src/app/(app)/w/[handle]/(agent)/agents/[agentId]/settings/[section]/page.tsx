import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { AgentMemorySettingsPage } from "@/features/agents/AgentMemorySettingsPage";
import { AgentSettingsPage } from "@/features/agents/AgentSettingsPage";
import { trpc } from "@/trpc/server";
import type { AgentFormSection } from "@/features/agents/components/AgentForm";

type SettingsSection = AgentFormSection | "memory" | "danger";

function parseSection(value: string): SettingsSection | null {
  switch (value) {
    case "profile":
    case "model":
    case "capabilities":
    case "admins":
    case "memory":
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
    if (section === "memory") {
      return <AgentMemorySettingsPage handle={handle} agent={agent} />;
    }
    return (
      <AgentSettingsPage handle={handle} agent={agent} section={section} />
    );
  } catch (e) {
    if (e instanceof TRPCError && e.code === "NOT_FOUND") {
      notFound();
    }
    throw e;
  }
}
