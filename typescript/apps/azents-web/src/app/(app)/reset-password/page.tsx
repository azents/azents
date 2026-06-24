import { PasswordResetPage } from "@/features/password-reset/pages/PasswordResetPage";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}): Promise<React.ReactElement> {
  const params = await searchParams;
  return <PasswordResetPage token={params.token ?? ""} />;
}
