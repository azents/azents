import { RuntimeWebAuthContainer } from "./containers/RuntimeWebAuthContainer";
import { runtimeWebAuthBootstrapScript } from "./runtimeWebAuthBootstrap";

interface RuntimeWebAuthPageProps {
  serviceId: string;
  mainWebOrigin: string | null;
  returnTarget: string;
}

export function RuntimeWebAuthPage({
  serviceId,
  mainWebOrigin,
  returnTarget,
}: RuntimeWebAuthPageProps): React.ReactElement {
  return (
    <>
      <RuntimeWebAuthContainer
        serviceId={serviceId}
        mainWebOrigin={mainWebOrigin}
        returnTarget={returnTarget}
      />
      <script
        dangerouslySetInnerHTML={{ __html: runtimeWebAuthBootstrapScript() }}
      />
    </>
  );
}
