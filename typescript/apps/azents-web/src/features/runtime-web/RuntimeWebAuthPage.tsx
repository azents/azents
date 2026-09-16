import { RuntimeWebAuth } from "./components/RuntimeWebAuth";

interface RuntimeWebAuthPageProps {
  serviceId: string;
}

export function RuntimeWebAuthPage({
  serviceId,
}: RuntimeWebAuthPageProps): React.ReactElement {
  return <RuntimeWebAuth serviceId={serviceId} />;
}
