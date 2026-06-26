import { ToolkitListPage } from "@/features/toolkits/ToolkitListPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <ToolkitListPage handle={handle} />;
}
