import { ToolkitFormPage } from "@/features/toolkits/ToolkitFormPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string; toolkitId: string }>;
}): Promise<React.ReactElement> {
  const { handle, toolkitId } = await params;
  return <ToolkitFormPage handle={handle} toolkitId={toolkitId} />;
}
