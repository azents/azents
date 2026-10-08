import { useEffect, useState } from "react";
import { startRuntimeWebAuth } from "../runtimeWebAuthBootstrap";
import type { RuntimeWebAuthState } from "../types";

interface RuntimeWebAuthContainerInput {
  serviceId: string;
  mainWebOrigin: string | null;
}

interface RuntimeWebAuthContainerOutput {
  serviceId: string;
  mainWebOrigin: string | null;
  state: RuntimeWebAuthState;
  onRetry: () => void;
}

export function useRuntimeWebAuthContainer({
  serviceId,
  mainWebOrigin,
}: RuntimeWebAuthContainerInput): RuntimeWebAuthContainerOutput {
  const [state, setState] = useState<RuntimeWebAuthState>({ type: "CHECKING" });
  useEffect(() => {
    let active = true;
    void startRuntimeWebAuth().then((result) => {
      if (active && result.type === "ERROR") {
        setState(result);
      }
    });
    return () => {
      active = false;
    };
  }, [serviceId, mainWebOrigin]);
  return {
    serviceId,
    mainWebOrigin,
    state,
    onRetry: (): void => window.location.reload(),
  };
}
