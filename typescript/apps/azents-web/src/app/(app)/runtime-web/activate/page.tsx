import { notFound, redirect } from "next/navigation";
import { RuntimeWebActivationPage } from "@/features/runtime-web/RuntimeWebActivationPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export const revalidate = 0;

interface RuntimeWebActivateRouteProps {
  searchParams: Promise<{ service_id?: string }>;
}

export default async function RuntimeWebActivateRoute({
  searchParams,
}: RuntimeWebActivateRouteProps): Promise<React.ReactElement> {
  const { service_id: serviceId } = await searchParams;
  if (serviceId == null || !/^[a-zA-Z0-9_-]{32}$/.test(serviceId)) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/activate?service_id=${encodeURIComponent(serviceId)}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return <RuntimeWebActivationPage serviceId={serviceId} />;
}
