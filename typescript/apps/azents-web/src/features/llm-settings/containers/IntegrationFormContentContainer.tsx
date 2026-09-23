"use client";

import { useState } from "react";
import type { IntegrationFormContentProps } from "../components/IntegrationFormModal";

type IntegrationFormContentContainerProps = Omit<
  IntegrationFormContentProps,
  "provider" | "name" | "onProviderChange" | "onNameChange"
> & {
  render: (props: IntegrationFormContentProps) => React.ReactElement;
};

export function IntegrationFormContentContainer({
  formModal,
  render,
  ...props
}: IntegrationFormContentContainerProps): React.ReactElement {
  const [provider, setProvider] = useState<string | null>(
    formModal.type === "EDIT" ? formModal.integration.provider : null,
  );
  const [name, setName] = useState(
    formModal.type === "EDIT" ? formModal.integration.name : "",
  );

  return render({
    ...props,
    formModal,
    provider,
    name,
    onProviderChange: setProvider,
    onNameChange: setName,
  });
}
