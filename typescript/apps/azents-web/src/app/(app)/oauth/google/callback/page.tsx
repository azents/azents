import { GoogleCallbackPage } from "@/features/toolkits/GoogleCallbackPage";
interface PageProps {
  searchParams: Promise<Record<string, string | string[] | null>>;
}
export default async function Page({
  searchParams,
}: PageProps): Promise<React.ReactElement> {
  const params = await searchParams;
  return (
    <GoogleCallbackPage
      code={typeof params.code === "string" ? params.code : null}
      state={typeof params.state === "string" ? params.state : null}
      providerError={typeof params.error === "string" ? params.error : null}
    />
  );
}
