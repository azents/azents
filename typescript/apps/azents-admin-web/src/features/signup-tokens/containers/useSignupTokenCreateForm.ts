"use client";
import { useForm } from "@mantine/form";
import type { SignupTokensPageContentProps } from "./useSignupTokensPageContainer";
import type { UseFormReturnType } from "@mantine/form";

export interface SignupTokenCreateFormProps {
  createState: SignupTokensPageContentProps["createState"];
  onCreateToken: (email: string) => void;
}
export interface SignupTokenCreateFormViewProps extends SignupTokenCreateFormProps {
  form: UseFormReturnType<{ email: string }>;
  handleSubmit: (values: { email: string }) => void;
}
export function useSignupTokenCreateForm(
  props: SignupTokenCreateFormProps,
): SignupTokenCreateFormViewProps {
  const form = useForm({
    mode: "controlled",
    initialValues: { email: "" },
    validate: {
      email: (value) => (value.trim().includes("@") ? null : "Enter an email."),
    },
  });
  function handleSubmit(values: { email: string }): void {
    props.onCreateToken(values.email.trim());
  }
  return { ...props, form, handleSubmit };
}
