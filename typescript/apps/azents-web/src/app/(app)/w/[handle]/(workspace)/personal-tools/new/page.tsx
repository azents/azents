import { PersonalToolkitFormPage } from "@/features/personal-tools/PersonalToolkitFormPage";
import { resolvePersonalToolsOrigin } from "@/features/personal-tools/resolve-personal-origin";

export default async function Page({
  searchParams,
  params,
}: {
  params: Promise<{ handle: string }>;
  searchParams: Promise<{
    originHandle?: string | string[];
    originAgentId?: string | string[];
    originSession?: string | string[];
  }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  const origin = await resolvePersonalToolsOrigin(await searchParams, handle);
  return (
    <PersonalToolkitFormPage key={handle} handle={handle} origin={origin} />
  );
}
