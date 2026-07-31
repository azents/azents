import { RuntimeProfilesPage } from "@/features/runtime-profiles/RuntimeProfilesPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <RuntimeProfilesPage handle={handle} />;
}
