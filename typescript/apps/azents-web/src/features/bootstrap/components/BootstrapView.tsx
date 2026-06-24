"use client";

import {
  Alert,
  Button,
  Loader,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useState } from "react";
import { FormPageLayout } from "@/shared/components/FormPageLayout";
import type { BootstrapContainerProps } from "../containers/useBootstrapContainer";
import type { BootstrapFormValues } from "../types";

const initialValues: BootstrapFormValues = {
  email: "",
  password: "",
  ownerName: "",
  workspaceName: "",
  workspaceHandle: "",
};

function BootstrapForm({
  error,
  submitting,
  onSubmit,
}: {
  error: string | null;
  submitting: boolean;
  onSubmit: (values: BootstrapFormValues) => void;
}): React.ReactElement {
  const [values, setValues] = useState(initialValues);

  function updateField(field: keyof BootstrapFormValues, value: string): void {
    setValues((current) => ({ ...current, [field]: value }));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    onSubmit(values);
  }

  return (
    <form onSubmit={handleSubmit}>
      <Stack gap="md">
        <Stack gap="xs" align="center">
          <Title order={2}>Set up Azents</Title>
          <Text c="dimmed">Create the first owner account and workspace.</Text>
        </Stack>
        {error ? <Alert color="red">{error}</Alert> : null}
        <TextInput
          label="Owner email"
          value={values.email}
          onChange={(event) => updateField("email", event.currentTarget.value)}
          autoComplete="email"
          disabled={submitting}
        />
        <PasswordInput
          label="Owner password"
          value={values.password}
          onChange={(event) =>
            updateField("password", event.currentTarget.value)
          }
          autoComplete="new-password"
          disabled={submitting}
        />
        <TextInput
          label="Owner name"
          value={values.ownerName}
          onChange={(event) =>
            updateField("ownerName", event.currentTarget.value)
          }
          disabled={submitting}
        />
        <TextInput
          label="Workspace name"
          value={values.workspaceName}
          onChange={(event) =>
            updateField("workspaceName", event.currentTarget.value)
          }
          disabled={submitting}
        />
        <TextInput
          label="Workspace handle"
          value={values.workspaceHandle}
          onChange={(event) =>
            updateField("workspaceHandle", event.currentTarget.value)
          }
          disabled={submitting}
        />
        <Button
          type="submit"
          size="lg"
          loading={submitting}
          disabled={submitting}
        >
          Create first owner
        </Button>
      </Stack>
    </form>
  );
}

export function BootstrapView({
  state,
  onSubmit,
}: BootstrapContainerProps): React.ReactElement {
  return (
    <FormPageLayout>
      {state.type === "LOADING" ? (
        <Stack align="center" gap="md">
          <Loader />
          <Text c="dimmed">Checking setup status…</Text>
        </Stack>
      ) : state.type === "UNAVAILABLE" ? (
        <Stack align="center" gap="md">
          <Title order={2}>Setup unavailable</Title>
          <Text c="dimmed">This instance already has an owner account.</Text>
        </Stack>
      ) : state.type === "SUCCESS" ? (
        <Stack align="center" gap="md">
          <Title order={2}>Setup complete</Title>
          <Text c="dimmed">Redirecting to login…</Text>
        </Stack>
      ) : (
        <BootstrapForm
          error={state.error}
          submitting={state.submitting}
          onSubmit={onSubmit}
        />
      )}
    </FormPageLayout>
  );
}
