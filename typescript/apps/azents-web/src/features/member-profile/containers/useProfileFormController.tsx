"use client";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import type { FormState } from "../types";
interface ProfileFormProps {
  name: string;
  formState: FormState;
  onSubmit: (name: string) => void;
  onResetForm: () => void;
}

export interface ProfileFormViewProps {
  formState: ProfileFormProps["formState"];
  onSubmit: ProfileFormProps["onSubmit"];
  t: ReturnType<typeof useTranslations<"memberProfile">>;
  name: string;
  setName: React.Dispatch<React.SetStateAction<string>>;
  nameError: string | null;
  setNameError: React.Dispatch<React.SetStateAction<string | null>>;
  handleSubmit: (e: React.FormEvent) => void;
  isSubmitting: boolean;
}
export function useProfileFormController({
  name: initialName,
  formState,
  onSubmit,
  onResetForm,
}: ProfileFormProps): ProfileFormViewProps {
  const t = useTranslations("memberProfile");
  const [name, setName] = useState(initialName);
  const [nameError, setNameError] = useState<string | null>(null);

  // Synchronize form values when server data updates
  useEffect(() => {
    setName(initialName);
  }, [initialName]);

  // Reset notification after a short time on success
  useEffect(() => {
    if (formState.type === "SUCCESS") {
      const timer = setTimeout(onResetForm, 3000);
      return () => clearTimeout(timer);
    }
  }, [formState.type, onResetForm]);

  const handleSubmit = (e: React.FormEvent): void => {
    e.preventDefault();

    const trimmedName = name.trim();
    if (trimmedName.length === 0) {
      setNameError(t("nameRequired"));
      return;
    }

    setNameError(null);
    onSubmit(trimmedName);
  };

  const isSubmitting = formState.type === "SUBMITTING";
  return {
    formState,
    onSubmit,
    t,
    name,
    setName,
    nameError,
    setNameError,
    handleSubmit,
    isSubmitting,
  };
}
