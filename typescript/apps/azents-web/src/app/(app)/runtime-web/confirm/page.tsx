import { notFound, redirect } from "next/navigation";
import { RuntimeWebConfirmationPage } from "@/features/runtime-web/RuntimeWebConfirmationPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export const revalidate = 0;

interface RuntimeWebConfirmRouteProps {
  searchParams: Promise<{ endpoint_id?: string }>;
}

export default async function RuntimeWebConfirmRoute({
  searchParams,
}: RuntimeWebConfirmRouteProps): Promise<React.ReactElement> {
  const { endpoint_id: endpointId } = await searchParams;
  if (endpointId == null || !/^[a-zA-Z0-9_-]{32}$/.test(endpointId)) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/confirm?endpoint_id=${encodeURIComponent(endpointId)}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return <RuntimeWebConfirmationPage endpointId={endpointId} />;
}
