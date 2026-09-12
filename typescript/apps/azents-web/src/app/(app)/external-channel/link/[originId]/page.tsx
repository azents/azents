import { LoginRequired } from "@/features/auth/components/LoginRequired";
import { ExternalAccountLinkConfirmationPage } from "@/features/external-account-links/ExternalAccountLinkConfirmationPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export default async function Page({
  params,
}: {
  params: Promise<{ originId: string }>;
}): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();
  if (authState.status !== "authenticated") {
    return <LoginRequired />;
  }

  const { originId } = await params;
  return <ExternalAccountLinkConfirmationPage originId={originId} />;
}
