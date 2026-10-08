import { RuntimeWebAuthContainer } from "./containers/RuntimeWebAuthContainer";
import { runtimeWebAuthBootstrapScript } from "./runtimeWebAuthBootstrap";

interface RuntimeWebAuthPageProps {
  serviceId: string;
  mainWebOrigin: string | null;
}

export function RuntimeWebAuthPage({
  serviceId,
  mainWebOrigin,
}: RuntimeWebAuthPageProps): React.ReactElement {
  return (
    <>
      <RuntimeWebAuthContainer
        serviceId={serviceId}
        mainWebOrigin={mainWebOrigin}
      />
      <script
        dangerouslySetInnerHTML={{ __html: runtimeWebAuthBootstrapScript() }}
      />
    </>
  );
}
