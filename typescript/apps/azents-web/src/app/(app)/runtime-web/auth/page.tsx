import { notFound, redirect } from "next/navigation";
import { RuntimeWebAuth } from "@/features/runtime-web/components/RuntimeWebAuth";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export const revalidate = 0;

interface RuntimeWebAuthPageProps {
  searchParams: Promise<{ endpoint_id?: string }>;
}

export default async function RuntimeWebAuthPage({
  searchParams,
}: RuntimeWebAuthPageProps): Promise<React.ReactElement> {
  const { endpoint_id: endpointId } = await searchParams;
  if (endpointId == null || !/^[a-zA-Z0-9_-]{32}$/.test(endpointId)) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/auth?endpoint_id=${encodeURIComponent(endpointId)}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return <RuntimeWebAuth endpointId={endpointId} />;
}
