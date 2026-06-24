"use client";

import { useCallback, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  CreatedPasswordResetToken,
  PasswordResetAdminState,
} from "../types";

export interface PasswordResetAdminContainerProps {
  state: PasswordResetAdminState;
  email: string;
  created: CreatedPasswordResetToken | null;
  creating: boolean;
  onEmailChange: (email: string) => void;
  onCreate: () => void;
  onRevoke: (tokenId: string) => void;
}

export function usePasswordResetAdminContainer(): PasswordResetAdminContainerProps {
  const utils = trpc.useUtils();
  const [email, setEmail] = useState("");
  const [created, setCreated] = useState<CreatedPasswordResetToken | null>(
    null,
  );
  const listQuery = trpc.passwordResetTokenAdmin.list.useQuery(void 0);
  const createMutation = trpc.passwordResetTokenAdmin.create.useMutation({
    onSuccess: (data) => {
      setCreated(data);
      void utils.passwordResetTokenAdmin.list.invalidate();
    },
  });
  const revokeMutation = trpc.passwordResetTokenAdmin.revoke.useMutation({
    onSuccess: () => {
      void utils.passwordResetTokenAdmin.list.invalidate();
    },
  });

  const state: PasswordResetAdminState = listQuery.isLoading
    ? { type: "LOADING" }
    : listQuery.error
      ? { type: "ERROR", message: listQuery.error.message }
      : { type: "LOADED", items: listQuery.data?.items ?? [] };

  const onEmailChange = useCallback((nextEmail: string): void => {
    setEmail(nextEmail);
  }, []);

  const onCreate = useCallback((): void => {
    setCreated(null);
    createMutation.mutate({ email });
  }, [createMutation, email]);

  const onRevoke = useCallback(
    (tokenId: string): void => {
      revokeMutation.mutate({ tokenId });
    },
    [revokeMutation],
  );

  return {
    state,
    email,
    created,
    creating: createMutation.isPending,
    onEmailChange,
    onCreate,
    onRevoke,
  };
}
