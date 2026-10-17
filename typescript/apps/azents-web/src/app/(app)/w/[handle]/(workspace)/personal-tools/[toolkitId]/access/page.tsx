import { PersonalAccessPage } from "@/features/personal-tools/PersonalAccessPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; toolkitId: string }>;
}): Promise<React.ReactElement> {
  const { handle, toolkitId } = await params;
  return (
    <PersonalAccessPage
      key={`${handle}:${toolkitId}`}
      type="connection"
      handle={handle}
      toolkitId={toolkitId}
    />
  );
}
