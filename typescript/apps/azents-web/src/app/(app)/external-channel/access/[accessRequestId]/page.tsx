import { ExternalChannelApprovalPage } from "@/features/external-channel-approval/ExternalChannelApprovalPage";

export default async function Page({
  params,
}: {
  params: Promise<{ accessRequestId: string }>;
}): Promise<React.ReactElement> {
  const { accessRequestId } = await params;
  return <ExternalChannelApprovalPage accessRequestId={accessRequestId} />;
}
