import { PersonalToolsPage } from "@/features/personal-tools/PersonalToolsPage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <PersonalToolsPage key={handle} handle={handle} />;
}
