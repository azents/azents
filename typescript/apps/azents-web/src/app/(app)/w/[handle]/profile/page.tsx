/**
 * Member profile edit route
 */
import { MemberProfilePage } from "@/features/member-profile/pages/MemberProfilePage";

export default async function Page({
  params,
}: {
  params: Promise<{ handle: string }>;
}): Promise<React.ReactElement> {
  const { handle } = await params;
  return <MemberProfilePage handle={handle} />;
}
