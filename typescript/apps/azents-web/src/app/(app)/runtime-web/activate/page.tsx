import { notFound, redirect } from "next/navigation";
import { RuntimeWebActivationPage } from "@/features/runtime-web/RuntimeWebActivationPage";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";
import { runtimeWebReturnTarget } from "@/shared/lib/runtime-web-return-target";

export const revalidate = 0;

interface RuntimeWebActivateRouteProps {
  searchParams: Promise<{ service_id?: string; return_to?: string }>;
}

export default async function RuntimeWebActivateRoute({
  searchParams,
}: RuntimeWebActivateRouteProps): Promise<React.ReactElement> {
  const { service_id: serviceId, return_to: target } = await searchParams;
  const returnTarget = runtimeWebReturnTarget(target ?? "/");
  if (
    serviceId == null ||
    !/^[a-zA-Z0-9_-]{32}$/.test(serviceId) ||
    returnTarget === null
  ) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/activate?${new URLSearchParams({ service_id: serviceId, return_to: returnTarget })}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return (
    <RuntimeWebActivationPage
      serviceId={serviceId}
      returnTarget={returnTarget}
    />
  );
}
