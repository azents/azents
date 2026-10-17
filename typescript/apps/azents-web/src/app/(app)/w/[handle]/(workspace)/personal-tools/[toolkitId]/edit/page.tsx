import { PersonalToolkitFormPage } from "@/features/personal-tools/PersonalToolkitFormPage";
import { resolvePersonalToolsOrigin } from "@/features/personal-tools/resolve-personal-origin";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ handle: string; toolkitId: string }>;
  searchParams: Promise<{
    originHandle?: string | string[];
    originAgentId?: string | string[];
    originSession?: string | string[];
  }>;
}): Promise<React.ReactElement> {
  const { handle, toolkitId } = await params;
  const origin = await resolvePersonalToolsOrigin(await searchParams, handle);
  return (
    <PersonalToolkitFormPage
      key={`${handle}:${typeof toolkitId === "undefined" ? "new" : toolkitId}`}
      handle={handle}
      toolkitId={toolkitId}
      origin={origin}
    />
  );
}
