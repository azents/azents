"use client";
import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef } from "react";
import { workspaceSchema } from "../schemas";
import type { UseFormReturnType } from "@mantine/form";

function toHandle(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}
export interface WorkspaceCreateFormInnerViewProps {
  error: {
    error: string | null;
    isPending: boolean;
    onSubmit: (data: {
      workspaceName: string;
      workspaceHandle: string;
      ownerName: string;
    }) => void;
  }["error"];
  isPending: {
    error: string | null;
    isPending: boolean;
    onSubmit: (data: {
      workspaceName: string;
      workspaceHandle: string;
      ownerName: string;
    }) => void;
  }["isPending"];
  onSubmit: {
    error: string | null;
    isPending: boolean;
    onSubmit: (data: {
      workspaceName: string;
      workspaceHandle: string;
      ownerName: string;
    }) => void;
  }["onSubmit"];
  t: ReturnType<typeof useTranslations<"workspaces">>;
  form: UseFormReturnType<
    { workspaceName: string; workspaceHandle: string; ownerName: string },
    { workspaceName: string; workspaceHandle: string; ownerName: string },
    (values: {
      workspaceName: string;
      workspaceHandle: string;
      ownerName: string;
    }) => Record<string, string>
  >;
  handleNameChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleHandleChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  handleSubmit: (values: {
    workspaceName: string;
    workspaceHandle: string;
    ownerName: string;
  }) => void;
}
export function useWorkspaceCreateFormInnerController({
  error,
  isPending,
  onSubmit,
}: {
  error: string | null;
  isPending: boolean;
  onSubmit: (data: {
    workspaceName: string;
    workspaceHandle: string;
    ownerName: string;
  }) => void;
}): WorkspaceCreateFormInnerViewProps {
  const t = useTranslations("workspaces");

  const form = useForm({
    mode: "controlled",
    initialValues: {
      workspaceName: "",
      workspaceHandle: "",
      ownerName: "",
    },
    validate: (values) => {
      const result = workspaceSchema.safeParse(values);
      if (result.success) {
        return {};
      }
      const errors: Record<string, string> = {};
      for (const issue of result.error.issues) {
        const path = issue.path.join(".");
        if (!path) {
          continue;
        }
        if (path === "workspaceName") {
          errors[path] = t("errors.nameRequired");
        } else if (path === "workspaceHandle") {
          errors[path] =
            issue.code === "invalid_format"
              ? t("errors.handleFormat")
              : t("errors.handleRequired");
        } else if (path === "ownerName") {
          errors[path] = t("errors.nameRequired");
        } else {
          errors[path] = issue.message;
        }
      }
      return errors;
    },
  });

  const handleEditedRef = useRef(false);

  const handleNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const name = e.currentTarget.value;
      form.setFieldValue("workspaceName", name);
      if (!handleEditedRef.current) {
        form.setFieldValue("workspaceHandle", toHandle(name));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
    [],
  );

  const handleHandleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      handleEditedRef.current = true;
      form.setFieldValue("workspaceHandle", e.currentTarget.value);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
    [],
  );

  useEffect(() => {
    if (error) {
      form.clearErrors();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- form is new reference every render
  }, [error]);

  function handleSubmit(values: typeof form.values): void {
    onSubmit({
      workspaceName: values.workspaceName.trim(),
      workspaceHandle: values.workspaceHandle.trim(),
      ownerName: values.ownerName.trim(),
    });
  }
  return {
    error,
    isPending,
    onSubmit,
    t,
    form,
    handleNameChange,
    handleHandleChange,
    handleSubmit,
  };
}
