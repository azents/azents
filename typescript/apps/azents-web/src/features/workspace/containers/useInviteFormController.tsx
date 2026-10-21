"use client";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import type { InviteFormState } from "../types";
import type { FormRulesRecord, UseFormReturnType } from "@mantine/form";
type InvitationRole = "member" | "manager";

export interface InviteFormViewProps {
  onClearInviteStatus: {
    inviteFormState: InviteFormState;
    onInvite: (email: string, role: "member" | "manager") => void;
    onClearInviteStatus: () => void;
  }["onClearInviteStatus"];
  t: ReturnType<typeof useTranslations<"workspace.dashboard">>;
  form: UseFormReturnType<
    { email: string; role: InvitationRole },
    { email: string; role: InvitationRole },
    FormRulesRecord<{ email: string; role: InvitationRole }>
  >;
  isSending: boolean;
  error: Extract<InviteFormState, { type: "IDLE" }>["error"];
  success: "inviteSuccess" | null;
  handleSubmit: (values: { email: string; role: InvitationRole }) => void;
}
export function useInviteFormController({
  inviteFormState,
  onInvite,
  onClearInviteStatus,
}: {
  inviteFormState: InviteFormState;
  onInvite: (email: string, role: "member" | "manager") => void;
  onClearInviteStatus: () => void;
}): InviteFormViewProps {
  const t = useTranslations("workspace.dashboard");

  const form = useForm<{ email: string; role: InvitationRole }>({
    mode: "controlled",
    initialValues: {
      email: "",
      role: "member",
    },
    validate: {
      email: (value) => (value.trim() ? null : t("inviteEmailRequired")),
    },
  });

  const isSending = inviteFormState.type === "SENDING";
  const error = inviteFormState.type === "IDLE" ? inviteFormState.error : null;
  const success =
    inviteFormState.type === "IDLE" ? inviteFormState.success : null;

  function handleSubmit(values: typeof form.values): void {
    onInvite(values.email.trim(), values.role);
    form.reset();
  }
  return {
    onClearInviteStatus,
    t,
    form,
    isSending,
    error,
    success,
    handleSubmit,
  };
}
