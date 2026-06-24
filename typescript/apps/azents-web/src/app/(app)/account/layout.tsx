/**
 * Account settings layout
 *
 * Account settings shell with auth check + sidebar navigation.
 */
import { LoginRequired } from "@/features/auth/components/LoginRequired";
import { AccountShell } from "@/shared/components/AccountShell";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export default async function AccountLayout({
  children,
}: {
  children: React.ReactNode;
}): Promise<React.ReactElement> {
  const authState = await getInitialAuthState();

  if (authState.status !== "authenticated") {
    return <LoginRequired />;
  }

  return <AccountShell>{children}</AccountShell>;
}
