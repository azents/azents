import { notFound, redirect } from "next/navigation";
import { RuntimeWebAuth } from "@/features/runtime-web/components/RuntimeWebAuth";
import { getInitialAuthState } from "@/shared/lib/getInitialAuthState";

export const revalidate = 0;

interface RuntimeWebAuthPageProps {
  searchParams: Promise<{ service_id?: string }>;
}

export default async function RuntimeWebAuthPage({
  searchParams,
}: RuntimeWebAuthPageProps): Promise<React.ReactElement> {
  const { service_id: serviceId } = await searchParams;
  if (serviceId == null || !/^[a-zA-Z0-9_-]{32}$/.test(serviceId)) {
    notFound();
  }
  const auth = await getInitialAuthState();
  if (auth.status === "unauthenticated") {
    const next = `/runtime-web/auth?service_id=${encodeURIComponent(serviceId)}`;
    redirect(`/login?next=${encodeURIComponent(next)}`);
  }
  return <RuntimeWebAuth serviceId={serviceId} />;
}
