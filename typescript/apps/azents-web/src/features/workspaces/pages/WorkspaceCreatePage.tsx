"use client";

/**
 * Workspace creation page
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceCreateForm } from "../components/WorkspaceCreateForm";
import { useWorkspaceCreate } from "../containers/useWorkspaceCreate";

export const WorkspaceCreatePage = createReactContainer(
  "WorkspaceCreatePage",
  useWorkspaceCreate,
  WorkspaceCreateForm,
);
