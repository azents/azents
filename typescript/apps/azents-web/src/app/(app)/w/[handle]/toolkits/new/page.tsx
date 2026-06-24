import { ToolkitFormPage } from "@/features/toolkits/ToolkitFormPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <ToolkitFormPage handle={handle} />;
}
