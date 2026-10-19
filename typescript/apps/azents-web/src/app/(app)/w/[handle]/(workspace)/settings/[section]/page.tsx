import { TRPCError } from "@trpc/server";
import { notFound } from "next/navigation";
import { WorkspaceSettingsSectionPage } from "@/features/llm-settings/WorkspaceSettingsSectionPage";
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
    return (
      <WorkspaceSettingsSectionPage
        section={section}
        handle={handle}
        workspace={workspace}
      />
    );
  } catch (error) {
    if (error instanceof TRPCError && error.code === "NOT_FOUND") {
      notFound();
    }
    throw error;
  }
}
