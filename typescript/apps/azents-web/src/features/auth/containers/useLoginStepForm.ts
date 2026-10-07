"use client";

/** Transient login form state, including browser autofill synchronization. */

import { useEffect, useRef, useState } from "react";
import type { LoginStepActions, LoginStepFormState } from "../types";
import type { FormEvent } from "react";

export function useLoginStepForm({
  emailAvailable,
  onSubmit,
  onRequestSignupEmail,
}: LoginStepActions): LoginStepFormState {
  const formRef = useRef<HTMLFormElement | null>(null);
  const [emailValid, setEmailValid] = useState(false);
  const [currentEmail, setCurrentEmail] = useState("");
  const [password, setPassword] = useState("");

  function syncFormState(): void {
    const input = formRef.current?.elements.namedItem("email");
    if (!(input instanceof HTMLInputElement)) {
      return;
    }
    const nextEmail = input.value;
    const trimmedEmail = nextEmail.trim();
    setCurrentEmail(trimmedEmail);
    setEmailValid(trimmedEmail.length > 0 && trimmedEmail.includes("@"));
    const passwordInput = formRef.current?.elements.namedItem("password");
    setPassword(
      passwordInput instanceof HTMLInputElement ? passwordInput.value : "",
    );
  }

  useEffect(() => {
    syncFormState();
    const intervalId = window.setInterval(syncFormState, 250);

    return () => {
      window.clearInterval(intervalId);
    };
  }, []);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const email = formData.get("email");
    const password = formData.get("password");
    if (
      typeof email === "string" &&
      email.trim() &&
      (emailAvailable || (typeof password === "string" && password.length > 0))
    ) {
      onSubmit(email.trim(), typeof password === "string" ? password : "");
    }
  }

  return {
    formRef,
    emailValid,
    passwordPresent: password.length > 0,
    onInput: syncFormState,
    onSubmit: handleSubmit,
    onRequestSignupEmail: () => onRequestSignupEmail(currentEmail),
  };
}
