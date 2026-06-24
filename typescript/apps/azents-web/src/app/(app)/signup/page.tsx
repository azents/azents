import { SignupPage } from "@/features/signup/pages/SignupPage";

interface PageProps {
  searchParams: Promise<{ token?: string }>;
}

export default async function Page({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const params = await searchParams;
  return <SignupPage token={params.token ?? ""} />;
}
