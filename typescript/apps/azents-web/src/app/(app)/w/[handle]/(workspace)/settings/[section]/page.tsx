import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { LlmIntegrationsPage } from "@/features/llm-settings/LlmIntegrationsPage";
import { WorkspaceModelSettingsPage } from "@/features/llm-settings/WorkspaceModelSettingsPage";
import { trpc } from "@/trpc/server";

type WorkspaceSettingsSection = "models" | "llm-integrations";

function parseSection(value: string): WorkspaceSettingsSection | null {
  switch (value) {
    case "models":
    case "llm-integrations":
      return value;
    default:
      return null;
  }
}

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; section: string }>;
}): Promise<React.ReactElement> {
  const { handle, section: rawSection } = await params;
  const section = parseSection(rawSection);
  if (section === null) {
    notFound();
  }

  try {
    const workspace = await trpc.workspace.get({ handle });
    if (section === "models") {
      return (
        <WorkspaceModelSettingsPage handle={handle} workspace={workspace} />
      );
    }
    return <LlmIntegrationsPage handle={handle} workspace={workspace} />;
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
