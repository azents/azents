"use client";

import { useEffect, useRef, useState } from "react";

export interface PasswordLoginFormInput {
  email: string;
  error: string | null;
  isPending: boolean;
  onSubmit: (password: string) => void;
  onUseOtherMethod: () => void;
}
export interface PasswordLoginFormOutput extends PasswordLoginFormInput {
  formRef: React.RefObject<HTMLFormElement | null>;
  password: string;
  syncPasswordState: () => void;
  handleSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}
export function usePasswordLoginFormController(
  props: PasswordLoginFormInput,
): PasswordLoginFormOutput {
  const formRef = useRef<HTMLFormElement | null>(null);
  const [password, setPassword] = useState("");
  function syncPasswordState(): void {
    const input = formRef.current?.elements.namedItem("password");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    setPassword(input.value);
  }
  useEffect(() => {
    syncPasswordState();
    const intervalId = window.setInterval(syncPasswordState, 250);
    return () => window.clearInterval(intervalId);
  }, []);
  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const password = new FormData(event.currentTarget).get("password");
    if (typeof password === "string" && password) {
      props.onSubmit(password);
    }
  }
  return { ...props, formRef, password, syncPasswordState, handleSubmit };
}
