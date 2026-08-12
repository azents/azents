"use client";

import {
  Alert,
  Anchor,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  NumberInput,
  Paper,
  Progress,
  rem,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useEffect, useState } from "react";
import { useConfig } from "@/config/client";
import { getPublicRoutePath } from "@/shared/lib/auth-policy";
import {
  baseResourceValue,
  byteUnits,
  cpuUnits,
  resourceUnitByValue,
  resourceUnitForValue,
  resourceUnitValue,
} from "../resourceUnits";
import type {
  InfrastructureProfileDeletionState,
  InfrastructureProfilesSectionProps,
  InfrastructureProfileSubmission,
} from "../containers/InfrastructureProfilesSectionContainer";
import type { InfrastructureProfileKind } from "../runtimeProviderPresentation";
import type {
  KubernetesToleration,
  RuntimeInfrastructureProfileDeletionImpactResponse,
  RuntimeInfrastructureProfileResponse,
} from "@azents/admin-client";

interface InfrastructureProfileFormValues {
  displayName: string;
  description: string;
  lifecycle: "active" | "disabled";
  schemaVersion: 1 | 2;
  runnerCpuRequest: number | null;
  runnerCpuLimit: number | null;
  runnerMemoryRequest: number | null;
  runnerMemoryLimit: number | null;
  storageClassName: string;
  storageRequestBytes: number;
  allowedCidrs: string;
  deniedCidrs: string;
  serviceAccountName: string;
  nodeSelector: string;
  tolerations: string;
  dindEnabled: boolean;
  dindCpuRequest: number | null;
  dindCpuLimit: number | null;
  dindMemoryRequest: number | null;
  dindMemoryLimit: number | null;
  dockerStorageBytes: number;
  sharedTemporaryStorageBytes: number;
  dockerCpuReservation: number | null;
  dockerCpuLimit: number | null;
  dockerMemoryReservation: number | null;
  dockerMemoryLimit: number | null;
  dockerNetworkName: string;
}

interface InfrastructureProfileFormUnits {
  runnerCpuRequest: string;
  runnerCpuLimit: string;
  runnerMemoryRequest: string;
  runnerMemoryLimit: string;
  storageRequestBytes: string;
  dindCpuRequest: string;
  dindCpuLimit: string;
  dindMemoryRequest: string;
  dindMemoryLimit: string;
  dockerStorageBytes: string;
  sharedTemporaryStorageBytes: string;
  dockerCpuReservation: string;
  dockerCpuLimit: string;
  dockerMemoryReservation: string;
  dockerMemoryLimit: string;
}

const gibibyte = 1024 * 1024 * 1024;

interface ProfileLabels {
  singular: string;
  plural: string;
}

function profileLabels(kind: InfrastructureProfileKind): ProfileLabels {
  return kind === "kubernetes_pod"
    ? { singular: "Pod Profile", plural: "Pod Profiles" }
    : { singular: "Container Profile", plural: "Container Profiles" };
}

function compatibilityMessage(reasonCode: string | null): string {
  switch (reasonCode) {
    case "provider_capability_missing":
      return "The Provider no longer advertises a required capability.";
    case "provider_capability_invalid":
      return "The Provider capability advertisement is invalid.";
    case "profile_contract_unsupported":
      return "The Provider does not support this Profile contract.";
    case null:
      return "The current Provider capabilities are incompatible.";
    default:
      return "The Profile cannot be used with the Provider's current capabilities.";
  }
}

function statusLabel(status: string): string {
  return status
    .split("_")
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function blankValues(): InfrastructureProfileFormValues {
  return {
    displayName: "",
    description: "",
    lifecycle: "active",
    schemaVersion: 1,
    runnerCpuRequest: null,
    runnerCpuLimit: null,
    runnerMemoryRequest: null,
    runnerMemoryLimit: null,
    storageClassName: "standard",
    storageRequestBytes: 10 * gibibyte,
    allowedCidrs: "",
    deniedCidrs: "",
    serviceAccountName: "",
    nodeSelector: "",
    tolerations: "",
    dindEnabled: false,
    dindCpuRequest: null,
    dindCpuLimit: null,
    dindMemoryRequest: null,
    dindMemoryLimit: null,
    dockerStorageBytes: 20 * gibibyte,
    sharedTemporaryStorageBytes: 4 * gibibyte,
    dockerCpuReservation: null,
    dockerCpuLimit: null,
    dockerMemoryReservation: null,
    dockerMemoryLimit: null,
    dockerNetworkName: "",
  };
}

function resourceUnitsForValues(
  values: InfrastructureProfileFormValues,
): InfrastructureProfileFormUnits {
  return {
    runnerCpuRequest: resourceUnitForValue(values.runnerCpuRequest, cpuUnits),
    runnerCpuLimit: resourceUnitForValue(values.runnerCpuLimit, cpuUnits),
    runnerMemoryRequest: resourceUnitForValue(
      values.runnerMemoryRequest,
      byteUnits,
    ),
    runnerMemoryLimit: resourceUnitForValue(
      values.runnerMemoryLimit,
      byteUnits,
    ),
    storageRequestBytes: resourceUnitForValue(
      values.storageRequestBytes,
      byteUnits,
    ),
    dindCpuRequest: resourceUnitForValue(values.dindCpuRequest, cpuUnits),
    dindCpuLimit: resourceUnitForValue(values.dindCpuLimit, cpuUnits),
    dindMemoryRequest: resourceUnitForValue(
      values.dindMemoryRequest,
      byteUnits,
    ),
    dindMemoryLimit: resourceUnitForValue(values.dindMemoryLimit, byteUnits),
    dockerStorageBytes: resourceUnitForValue(
      values.dockerStorageBytes,
      byteUnits,
    ),
    sharedTemporaryStorageBytes: resourceUnitForValue(
      values.sharedTemporaryStorageBytes,
      byteUnits,
    ),
    dockerCpuReservation: resourceUnitForValue(
      values.dockerCpuReservation,
      cpuUnits,
    ),
    dockerCpuLimit: resourceUnitForValue(values.dockerCpuLimit, cpuUnits),
    dockerMemoryReservation: resourceUnitForValue(
      values.dockerMemoryReservation,
      byteUnits,
    ),
    dockerMemoryLimit: resourceUnitForValue(
      values.dockerMemoryLimit,
      byteUnits,
    ),
  };
}

function lines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function nodeSelectorFromText(value: string): Record<string, string> {
  return Object.fromEntries(
    lines(value).map((line) => {
      const separator = line.indexOf("=");
      return separator < 1
        ? [line, ""]
        : [line.slice(0, separator).trim(), line.slice(separator + 1).trim()];
    }),
  );
}

function nodeSelectorToText(value?: Record<string, string>): string {
  return Object.entries(value ?? {})
    .map(([key, item]) => `${key}=${item}`)
    .join("\n");
}

function tolerationsFromText(value: string): KubernetesToleration[] {
  return lines(value).map((line) => {
    const [key = "", operator = "Equal", itemValue, effect, seconds] = line
      .split("|")
      .map((item) => item.trim());
    return {
      key,
      operator: operator === "Exists" ? "Exists" : "Equal",
      value: itemValue ? itemValue : null,
      effect:
        effect === "NoSchedule" ||
        effect === "PreferNoSchedule" ||
        effect === "NoExecute"
          ? effect
          : null,
      toleration_seconds: seconds ? Number(seconds) : null,
    };
  });
}

function tolerationsToText(tolerations?: KubernetesToleration[]): string {
  return (tolerations ?? [])
    .map((item) =>
      [
        item.key,
        item.operator,
        item.value ?? "",
        item.effect ?? "",
        item.toleration_seconds?.toString() ?? "",
      ].join("|"),
    )
    .join("\n");
}

function valuesFromProfile(
  profile: RuntimeInfrastructureProfileResponse,
): InfrastructureProfileFormValues {
  const base = blankValues();
  const spec = profile.spec;
  if (spec === null) {
    throw new Error("The infrastructure Profile document is unavailable.");
  }
  if (spec.profile_kind === "kubernetes_pod") {
    return {
      ...base,
      displayName: profile.display_name,
      description: profile.description,
      lifecycle: profile.lifecycle,
      schemaVersion: spec.schema_version,
      runnerCpuRequest: spec.runner_resources.cpu_request_millicores,
      runnerCpuLimit: spec.runner_resources.cpu_limit_millicores,
      runnerMemoryRequest: spec.runner_resources.memory_request_bytes,
      runnerMemoryLimit: spec.runner_resources.memory_limit_bytes,
      storageClassName: spec.workspace_volume.storage_class_name,
      storageRequestBytes: spec.workspace_volume.storage_request_bytes,
      allowedCidrs: (spec.network_policy.allowed_cidrs ?? []).join("\n"),
      deniedCidrs: (spec.network_policy.denied_cidrs ?? []).join("\n"),
      serviceAccountName: spec.service_account_name ?? "",
      nodeSelector: nodeSelectorToText(spec.scheduling.node_selector),
      tolerations: tolerationsToText(spec.scheduling.tolerations),
      dindEnabled: spec.dind !== null,
      dindCpuRequest:
        spec.dind?.engine_resources.cpu_request_millicores ?? null,
      dindCpuLimit: spec.dind?.engine_resources.cpu_limit_millicores ?? null,
      dindMemoryRequest:
        spec.dind?.engine_resources.memory_request_bytes ?? null,
      dindMemoryLimit: spec.dind?.engine_resources.memory_limit_bytes ?? null,
      dockerStorageBytes:
        spec.dind?.docker_storage_bytes ?? base.dockerStorageBytes,
      sharedTemporaryStorageBytes:
        spec.dind?.shared_temporary_storage_bytes ??
        base.sharedTemporaryStorageBytes,
    };
  }
  return {
    ...base,
    displayName: profile.display_name,
    description: profile.description,
    lifecycle: profile.lifecycle,
    schemaVersion: spec.schema_version,
    dockerCpuReservation: spec.runner_resources.cpu_reservation_millicores,
    dockerCpuLimit: spec.runner_resources.cpu_limit_millicores,
    dockerMemoryReservation: spec.runner_resources.memory_reservation_bytes,
    dockerMemoryLimit: spec.runner_resources.memory_limit_bytes,
    dockerNetworkName: spec.network_name ?? "",
  };
}

function buildSpec(
  kind: InfrastructureProfileKind,
  values: InfrastructureProfileFormValues,
): InfrastructureProfileSubmission["spec"] {
  if (kind === "kubernetes_pod") {
    const runnerResources = {
      cpu_request_millicores: values.runnerCpuRequest,
      cpu_limit_millicores: values.runnerCpuLimit,
      memory_request_bytes: values.runnerMemoryRequest,
      memory_limit_bytes: values.runnerMemoryLimit,
    };
    const workspaceVolume = {
      storage_class_name: values.storageClassName,
      storage_request_bytes: values.storageRequestBytes,
    };
    const networkPolicy = {
      allowed_cidrs: lines(values.allowedCidrs),
      denied_cidrs: lines(values.deniedCidrs),
    };
    const scheduling = {
      node_selector: nodeSelectorFromText(values.nodeSelector),
      tolerations: tolerationsFromText(values.tolerations),
    };
    const dind = values.dindEnabled
      ? {
          engine_resources: {
            cpu_request_millicores: values.dindCpuRequest,
            cpu_limit_millicores: values.dindCpuLimit,
            memory_request_bytes: values.dindMemoryRequest,
            memory_limit_bytes: values.dindMemoryLimit,
          },
          docker_storage_bytes: values.dockerStorageBytes,
          shared_temporary_storage_bytes: values.sharedTemporaryStorageBytes,
        }
      : null;
    if (values.schemaVersion === 2) {
      return {
        profile_kind: "kubernetes_pod",
        contract_family: "kubernetes.pod-profile",
        schema_version: 2,
        runner_resources: runnerResources,
        workspace_volume: workspaceVolume,
        network_policy: networkPolicy,
        service_account_name: values.serviceAccountName.trim() || null,
        scheduling,
        dind,
      };
    }
    return {
      profile_kind: "kubernetes_pod",
      contract_family: "kubernetes.pod-profile",
      schema_version: 1,
      runner_resources: runnerResources,
      workspace_volume: workspaceVolume,
      network_policy: networkPolicy,
      service_account_name: values.serviceAccountName.trim() || null,
      scheduling,
      dind,
    };
  }
  const runnerResources = {
    cpu_reservation_millicores: values.dockerCpuReservation,
    cpu_limit_millicores: values.dockerCpuLimit,
    memory_reservation_bytes: values.dockerMemoryReservation,
    memory_limit_bytes: values.dockerMemoryLimit,
  };
  if (values.schemaVersion === 2) {
    return {
      profile_kind: "docker_container",
      contract_family: "docker.container-profile",
      schema_version: 2,
      runner_resources: runnerResources,
      network_name: values.dockerNetworkName.trim() || null,
    };
  }
  return {
    profile_kind: "docker_container",
    contract_family: "docker.container-profile",
    schema_version: 1,
    runner_resources: runnerResources,
    network_name: values.dockerNetworkName.trim() || null,
  };
}

function QuantityInput({
  label,
  value,
  unit,
  units,
  minBaseValue,
  allowDecimal,
  decimalScale,
  step,
  onChange,
  onUnitChange,
}: {
  label: string;
  value: number | null;
  unit: string;
  units: readonly {
    value: string;
    label: string;
    multiplier: number;
  }[];
  minBaseValue: number;
  allowDecimal: boolean;
  decimalScale?: number;
  step: number;
  onChange: (value: number | null) => void;
  onUnitChange: (unit: string) => void;
}): React.ReactElement {
  const selectedUnit = resourceUnitByValue(unit, units);
  if (selectedUnit === null) {
    throw new Error("The selected resource unit must be configured.");
  }
  const acceptsDecimal = allowDecimal && selectedUnit.multiplier > 1;

  return (
    <Group align="flex-end" gap="xs" wrap="nowrap">
      <NumberInput
        label={label}
        value={resourceUnitValue(value, selectedUnit) ?? ""}
        min={0}
        allowDecimal={acceptsDecimal}
        decimalScale={acceptsDecimal ? decimalScale : 0}
        step={step}
        style={{ flex: 1 }}
        onChange={(nextValue) => {
          if (nextValue === "") {
            onChange(null);
            return;
          }
          if (typeof nextValue !== "number") {
            return;
          }

          const nextBaseValue = baseResourceValue(nextValue, selectedUnit);
          onChange(
            nextBaseValue !== null && nextBaseValue >= minBaseValue
              ? nextBaseValue
              : null,
          );
        }}
      />
      <Select
        label="Unit"
        data={units.map((item) => ({
          value: item.value,
          label: item.label,
        }))}
        value={unit}
        allowDeselect={false}
        w={rem(140)}
        onChange={(nextUnit) => {
          const configuredUnit = resourceUnitByValue(nextUnit, units);
          if (configuredUnit !== null) {
            onUnitChange(configuredUnit.value);
          }
        }}
      />
    </Group>
  );
}

function ResourceFields({
  prefix,
  values,
  units,
  onChange,
  onUnitChange,
}: {
  prefix: "runner" | "dind";
  values: InfrastructureProfileFormValues;
  units: InfrastructureProfileFormUnits;
  onChange: (
    field: keyof InfrastructureProfileFormValues,
    value: number | null,
  ) => void;
  onUnitChange: (
    field: keyof InfrastructureProfileFormUnits,
    unit: string,
  ) => void;
}): React.ReactElement {
  const cpuRequest =
    prefix === "runner" ? values.runnerCpuRequest : values.dindCpuRequest;
  const cpuLimit =
    prefix === "runner" ? values.runnerCpuLimit : values.dindCpuLimit;
  const memoryRequest =
    prefix === "runner" ? values.runnerMemoryRequest : values.dindMemoryRequest;
  const memoryLimit =
    prefix === "runner" ? values.runnerMemoryLimit : values.dindMemoryLimit;
  const field = (
    runner: keyof InfrastructureProfileFormValues,
    dind: keyof InfrastructureProfileFormValues,
  ): keyof InfrastructureProfileFormValues =>
    prefix === "runner" ? runner : dind;
  const unitField = (
    runner: keyof InfrastructureProfileFormUnits,
    dind: keyof InfrastructureProfileFormUnits,
  ): keyof InfrastructureProfileFormUnits =>
    prefix === "runner" ? runner : dind;

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <QuantityInput
        label="CPU request"
        value={cpuRequest}
        unit={units[unitField("runnerCpuRequest", "dindCpuRequest")]}
        units={cpuUnits}
        minBaseValue={0}
        allowDecimal
        decimalScale={3}
        step={0.1}
        onChange={(value) =>
          onChange(field("runnerCpuRequest", "dindCpuRequest"), value)
        }
        onUnitChange={(unit) =>
          onUnitChange(unitField("runnerCpuRequest", "dindCpuRequest"), unit)
        }
      />
      <QuantityInput
        label="CPU limit"
        value={cpuLimit}
        unit={units[unitField("runnerCpuLimit", "dindCpuLimit")]}
        units={cpuUnits}
        minBaseValue={0}
        allowDecimal
        decimalScale={3}
        step={0.1}
        onChange={(value) =>
          onChange(field("runnerCpuLimit", "dindCpuLimit"), value)
        }
        onUnitChange={(unit) =>
          onUnitChange(unitField("runnerCpuLimit", "dindCpuLimit"), unit)
        }
      />
      <QuantityInput
        label="Memory request"
        value={memoryRequest}
        unit={units[unitField("runnerMemoryRequest", "dindMemoryRequest")]}
        units={byteUnits}
        minBaseValue={0}
        allowDecimal
        decimalScale={10}
        step={1}
        onChange={(value) =>
          onChange(field("runnerMemoryRequest", "dindMemoryRequest"), value)
        }
        onUnitChange={(unit) =>
          onUnitChange(
            unitField("runnerMemoryRequest", "dindMemoryRequest"),
            unit,
          )
        }
      />
      <QuantityInput
        label="Memory limit"
        value={memoryLimit}
        unit={units[unitField("runnerMemoryLimit", "dindMemoryLimit")]}
        units={byteUnits}
        minBaseValue={0}
        allowDecimal
        decimalScale={10}
        step={1}
        onChange={(value) =>
          onChange(field("runnerMemoryLimit", "dindMemoryLimit"), value)
        }
        onUnitChange={(unit) =>
          onUnitChange(unitField("runnerMemoryLimit", "dindMemoryLimit"), unit)
        }
      />
    </SimpleGrid>
  );
}

function InfrastructureProfileEditor({
  kind,
  editorState,
  submitting,
  errorMessage,
  onClose,
  onSubmit,
}: Pick<
  InfrastructureProfilesSectionProps,
  "editorState" | "submitting" | "errorMessage" | "onCloseEditor" | "onSubmit"
> & {
  kind: InfrastructureProfileKind;
  onClose: () => void;
}): React.ReactElement {
  const labels = profileLabels(kind);
  const form = useForm<InfrastructureProfileFormValues>({
    mode: "controlled",
    initialValues: blankValues(),
    validate: {
      displayName: (value) => (value.trim() ? null : "Name is required."),
      storageClassName: (value) =>
        kind === "kubernetes_pod" && !value.trim()
          ? "Storage class is required."
          : null,
      nodeSelector: (value) =>
        lines(value).some((line) => !line.includes("="))
          ? "Use one key=value selector per line."
          : null,
      tolerations: (value) =>
        lines(value).some((line) => line.split("|").length < 2)
          ? "Use key|operator|value|effect|seconds."
          : null,
    },
  });
  const [units, setUnits] = useState<InfrastructureProfileFormUnits>(() =>
    resourceUnitsForValues(blankValues()),
  );

  useEffect(() => {
    const nextValues =
      editorState.type === "EDIT"
        ? valuesFromProfile(editorState.profile)
        : blankValues();
    form.setValues(nextValues);
    setUnits(resourceUnitsForValues(nextValues));
    form.resetDirty();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the selected editor target changes.
  }, [editorState]);

  const setNumber = (
    field: keyof InfrastructureProfileFormValues,
    value: number | null,
  ): void => {
    form.setFieldValue(field, value);
  };
  const setUnit = (
    field: keyof InfrastructureProfileFormUnits,
    unit: string,
  ): void => {
    setUnits((currentUnits) => ({ ...currentUnits, [field]: unit }));
  };

  return (
    <Modal
      opened={editorState.type !== "CLOSED"}
      onClose={onClose}
      title={
        editorState.type === "EDIT"
          ? `Edit ${labels.singular}`
          : `Create ${labels.singular}`
      }
      size="xl"
    >
      <form
        onSubmit={form.onSubmit((values) =>
          onSubmit({
            displayName: values.displayName.trim(),
            description: values.description.trim(),
            lifecycle: values.lifecycle,
            spec: buildSpec(kind, values),
          }),
        )}
      >
        <Stack gap="md">
          <TextInput
            label="Name"
            required
            key={form.key("displayName")}
            {...form.getInputProps("displayName")}
          />
          <Textarea
            label="Description"
            key={form.key("description")}
            {...form.getInputProps("description")}
          />
          <Select
            label="Lifecycle"
            data={[
              { value: "active", label: "Active" },
              { value: "disabled", label: "Disabled" },
            ]}
            allowDeselect={false}
            key={form.key("lifecycle")}
            {...form.getInputProps("lifecycle")}
          />

          {kind === "kubernetes_pod" ? (
            <>
              <Divider label="Runner resources" />
              <ResourceFields
                prefix="runner"
                values={form.values}
                units={units}
                onChange={setNumber}
                onUnitChange={setUnit}
              />
              <Divider label="Workspace volume" />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextInput
                  label="Storage class"
                  required
                  key={form.key("storageClassName")}
                  {...form.getInputProps("storageClassName")}
                />
                <QuantityInput
                  label="Storage request"
                  value={form.values.storageRequestBytes}
                  unit={units.storageRequestBytes}
                  units={byteUnits}
                  minBaseValue={1}
                  allowDecimal
                  decimalScale={10}
                  step={1}
                  onChange={(value) =>
                    form.setFieldValue("storageRequestBytes", value ?? 1)
                  }
                  onUnitChange={(unit) => setUnit("storageRequestBytes", unit)}
                />
              </SimpleGrid>
              <Divider label="Network and identity" />
              <Textarea
                label="Allowed CIDRs"
                description="One CIDR per line."
                minRows={2}
                key={form.key("allowedCidrs")}
                {...form.getInputProps("allowedCidrs")}
              />
              <Textarea
                label="Denied CIDRs"
                description="One CIDR per line."
                minRows={2}
                key={form.key("deniedCidrs")}
                {...form.getInputProps("deniedCidrs")}
              />
              <TextInput
                label="ServiceAccount name"
                key={form.key("serviceAccountName")}
                {...form.getInputProps("serviceAccountName")}
              />
              <Divider label="Scheduling" />
              <Textarea
                label="Node selector"
                description="One key=value selector per line."
                minRows={2}
                key={form.key("nodeSelector")}
                {...form.getInputProps("nodeSelector")}
              />
              <Textarea
                label="Tolerations"
                description="One key|operator|value|effect|seconds entry per line."
                minRows={2}
                key={form.key("tolerations")}
                {...form.getInputProps("tolerations")}
              />
              <Divider label="Docker-in-Docker" />
              <Switch
                label="Enable DinD topology"
                checked={form.values.dindEnabled}
                onChange={(event) =>
                  form.setFieldValue("dindEnabled", event.currentTarget.checked)
                }
              />
              {form.values.dindEnabled && (
                <>
                  <ResourceFields
                    prefix="dind"
                    values={form.values}
                    units={units}
                    onChange={setNumber}
                    onUnitChange={setUnit}
                  />
                  <SimpleGrid cols={{ base: 1, sm: 2 }}>
                    <QuantityInput
                      label="Docker storage"
                      value={form.values.dockerStorageBytes}
                      unit={units.dockerStorageBytes}
                      units={byteUnits}
                      minBaseValue={1}
                      allowDecimal
                      decimalScale={10}
                      step={1}
                      onChange={(value) =>
                        form.setFieldValue("dockerStorageBytes", value ?? 1)
                      }
                      onUnitChange={(unit) =>
                        setUnit("dockerStorageBytes", unit)
                      }
                    />
                    <QuantityInput
                      label="Shared temporary storage"
                      value={form.values.sharedTemporaryStorageBytes}
                      unit={units.sharedTemporaryStorageBytes}
                      units={byteUnits}
                      minBaseValue={1}
                      allowDecimal
                      decimalScale={10}
                      step={1}
                      onChange={(value) =>
                        form.setFieldValue(
                          "sharedTemporaryStorageBytes",
                          value ?? 1,
                        )
                      }
                      onUnitChange={(unit) =>
                        setUnit("sharedTemporaryStorageBytes", unit)
                      }
                    />
                  </SimpleGrid>
                </>
              )}
            </>
          ) : (
            <>
              <Divider label="Container resources" />
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <QuantityInput
                  label="CPU reservation"
                  value={form.values.dockerCpuReservation}
                  unit={units.dockerCpuReservation}
                  units={cpuUnits}
                  minBaseValue={0}
                  allowDecimal
                  decimalScale={3}
                  step={0.1}
                  onChange={(value) => setNumber("dockerCpuReservation", value)}
                  onUnitChange={(unit) => setUnit("dockerCpuReservation", unit)}
                />
                <QuantityInput
                  label="CPU limit"
                  value={form.values.dockerCpuLimit}
                  unit={units.dockerCpuLimit}
                  units={cpuUnits}
                  minBaseValue={0}
                  allowDecimal
                  decimalScale={3}
                  step={0.1}
                  onChange={(value) => setNumber("dockerCpuLimit", value)}
                  onUnitChange={(unit) => setUnit("dockerCpuLimit", unit)}
                />
                <QuantityInput
                  label="Memory reservation"
                  value={form.values.dockerMemoryReservation}
                  unit={units.dockerMemoryReservation}
                  units={byteUnits}
                  minBaseValue={0}
                  allowDecimal
                  decimalScale={10}
                  step={1}
                  onChange={(value) =>
                    setNumber("dockerMemoryReservation", value)
                  }
                  onUnitChange={(unit) =>
                    setUnit("dockerMemoryReservation", unit)
                  }
                />
                <QuantityInput
                  label="Memory limit"
                  value={form.values.dockerMemoryLimit}
                  unit={units.dockerMemoryLimit}
                  units={byteUnits}
                  minBaseValue={0}
                  allowDecimal
                  decimalScale={10}
                  step={1}
                  onChange={(value) => setNumber("dockerMemoryLimit", value)}
                  onUnitChange={(unit) => setUnit("dockerMemoryLimit", unit)}
                />
              </SimpleGrid>
              <TextInput
                label="Docker network name"
                description="Leave empty to omit an explicit Docker network."
                key={form.key("dockerNetworkName")}
                {...form.getInputProps("dockerNetworkName")}
              />
            </>
          )}

          {errorMessage !== null && <Alert color="red">{errorMessage}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" loading={submitting}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Modal>
  );
}

function DeletionImpactSummary({
  impact,
  onPreviousReferences,
  onNextReferences,
}: {
  impact: RuntimeInfrastructureProfileDeletionImpactResponse;
  onPreviousReferences: () => void;
  onNextReferences: () => void;
}): React.ReactElement {
  const { publicBaseUrl } = useConfig();

  return (
    <Stack gap="sm">
      {impact.applied_only_running_runtime_count > 0 ? (
        <Alert color="yellow" title="Running Runtimes retain this Profile">
          {impact.applied_only_running_runtime_count} currently running{" "}
          {impact.applied_only_running_runtime_count === 1
            ? "Runtime retains"
            : "Runtimes retain"}{" "}
          this Profile only in applied configuration. Deletion will not stop,
          restart, recreate, reset, or change those Runtimes or their Workspace
          storage.
        </Alert>
      ) : (
        <Text size="sm" c="dimmed">
          No currently running Runtime retains this Profile only in applied
          configuration.
        </Text>
      )}

      {impact.blocking_reference_count > 0 && (
        <>
          <Alert color="red" title="Deletion is blocked">
            {impact.blocking_reference_count} current Workspace Runtime{" "}
            {impact.blocking_reference_count === 1
              ? "Profile references"
              : "Profiles reference"}{" "}
            this infrastructure Profile. Move every current reference before
            deleting.
          </Alert>
          <Text size="xs" c="dimmed">
            Showing {impact.offset + 1}–
            {impact.offset + impact.references.length} of{" "}
            {impact.blocking_reference_count} current references.
          </Text>
          <ScrollArea mah={rem(320)} type="auto">
            <Stack gap="xs">
              {impact.references.map((reference) => (
                <Paper
                  key={reference.workspace_runtime_profile_id}
                  withBorder
                  p="sm"
                >
                  <Stack gap={4}>
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={0}>
                        <Text fw={600} style={{ overflowWrap: "anywhere" }}>
                          {reference.workspace_name}
                        </Text>
                        <Text size="xs" c="dimmed">
                          @{reference.workspace_handle}
                        </Text>
                      </Stack>
                      <Badge
                        color={
                          reference.workspace_runtime_profile_lifecycle ===
                          "active"
                            ? "green"
                            : "gray"
                        }
                        variant="light"
                      >
                        {reference.workspace_runtime_profile_lifecycle}
                      </Badge>
                    </Group>
                    <Text
                      size="sm"
                      fw={500}
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {reference.workspace_runtime_profile_display_name}
                    </Text>
                    <Text
                      size="xs"
                      c="dimmed"
                      ff="monospace"
                      style={{ overflowWrap: "anywhere" }}
                    >
                      {reference.workspace_runtime_profile_id}
                    </Text>
                    <Group gap="xs">
                      <Badge variant="outline">
                        {reference.selected_agent_count} selected{" "}
                        {reference.selected_agent_count === 1
                          ? "Agent"
                          : "Agents"}
                      </Badge>
                      <Badge variant="outline">
                        {reference.running_runtime_count} running{" "}
                        {reference.running_runtime_count === 1
                          ? "Runtime"
                          : "Runtimes"}
                      </Badge>
                    </Group>
                    <Anchor
                      href={getPublicRoutePath(
                        publicBaseUrl,
                        `/workspaces/${encodeURIComponent(reference.workspace_handle)}/runtime-profiles/${encodeURIComponent(reference.workspace_runtime_profile_id)}`,
                      )}
                      target="_blank"
                      rel="noopener noreferrer"
                      size="sm"
                    >
                      Open details in new tab
                    </Anchor>
                  </Stack>
                </Paper>
              ))}
            </Stack>
          </ScrollArea>
          <Group justify="space-between">
            <Button
              size="xs"
              variant="default"
              disabled={impact.offset === 0}
              onClick={onPreviousReferences}
            >
              Previous references
            </Button>
            <Button
              size="xs"
              variant="default"
              disabled={
                impact.offset + impact.references.length >=
                impact.blocking_reference_count
              }
              onClick={onNextReferences}
            >
              Next references
            </Button>
          </Group>
        </>
      )}
    </Stack>
  );
}

function InfrastructureProfileDeletionModal({
  state,
  onClose,
  onRetryImpact,
  onPreviousReferences,
  onNextReferences,
  onConfirm,
}: {
  state: InfrastructureProfileDeletionState;
  onClose: () => void;
  onRetryImpact: () => void;
  onPreviousReferences: () => void;
  onNextReferences: () => void;
  onConfirm: () => void;
}): React.ReactElement | null {
  if (state.type === "CLOSED") {
    return null;
  }
  const deleting = state.type === "DELETING";
  const impact =
    state.type === "READY" ||
    state.type === "BLOCKED" ||
    state.type === "DELETING" ||
    state.type === "DELETE_ERROR"
      ? state.impact
      : null;

  return (
    <Modal
      opened
      onClose={onClose}
      title={`Delete ${state.profile.display_name}`}
      size="lg"
      closeOnClickOutside={!deleting}
      closeOnEscape={!deleting}
      withCloseButton={!deleting}
    >
      <Stack gap="md">
        <Stack gap={2}>
          <Text size="sm">
            Permanently delete this{" "}
            {state.profile.profile_kind === "kubernetes_pod"
              ? "Pod Profile"
              : "Container Profile"}
            .
          </Text>
          <Text
            size="xs"
            c="dimmed"
            ff="monospace"
            style={{ overflowWrap: "anywhere" }}
          >
            {state.profile.id}
          </Text>
        </Stack>

        {state.type === "LOADING" && (
          <Group gap="sm">
            <Loader size="sm" />
            <Text size="sm">Loading current deletion impact…</Text>
          </Group>
        )}
        {state.type === "IMPACT_ERROR" && (
          <Alert color="red" title="Could not load current impact">
            {state.message}
          </Alert>
        )}
        {state.type === "DELETE_ERROR" && (
          <Alert color="red" title="Profile was not deleted">
            {state.message}
          </Alert>
        )}
        {state.type === "READY" && (
          <Alert color="red" title="Permanent deletion">
            No current Workspace Runtime Profile references this Profile. This
            action permanently removes only the infrastructure Profile and
            cannot be undone.
          </Alert>
        )}
        {state.type === "DELETING" && (
          <Alert color="blue" title="Deleting Profile">
            Current references are being rechecked atomically before the Profile
            is removed.
          </Alert>
        )}
        {impact !== null && (
          <DeletionImpactSummary
            impact={impact}
            onPreviousReferences={onPreviousReferences}
            onNextReferences={onNextReferences}
          />
        )}

        <Group justify="flex-end">
          {!deleting && (
            <Button variant="default" onClick={onClose}>
              Cancel
            </Button>
          )}
          {(state.type === "IMPACT_ERROR" ||
            state.type === "BLOCKED" ||
            state.type === "DELETE_ERROR") && (
            <Button variant="light" onClick={onRetryImpact}>
              Refresh impact
            </Button>
          )}
          {state.type === "READY" && (
            <Button color="red" onClick={onConfirm}>
              Delete permanently
            </Button>
          )}
          {state.type === "DELETING" && (
            <Button color="red" loading>
              Deleting
            </Button>
          )}
        </Group>
      </Stack>
    </Modal>
  );
}

export function InfrastructureProfilesSection({
  profileKind,
  state,
  editorState,
  operationState,
  deletionState,
  submitting,
  errorMessage,
  onOpenCreate,
  onOpenEdit,
  onCloseEditor,
  onSubmit,
  onRecreate,
  onRecreateProvider,
  onOpenDelete,
  onCloseDeletion,
  onRetryDeletionImpact,
  onPreviousDeletionReferences,
  onNextDeletionReferences,
  onConfirmDeletion,
}: InfrastructureProfilesSectionProps): React.ReactElement {
  if (profileKind === null || state.type === "IDLE") {
    return (
      <Alert color="gray">
        Provider Profiles are not available for this Provider kind.
      </Alert>
    );
  }

  const labels = profileLabels(profileKind);

  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            {labels.plural}
          </Text>
          <Text size="xs" c="dimmed">
            Provider-owned typed presets used by Workspace Runtime Profiles.
          </Text>
        </Stack>
        <Group gap="xs">
          <Button
            size="xs"
            variant="default"
            loading={submitting}
            onClick={onRecreateProvider}
          >
            Recreate Provider Runtimes
          </Button>
          <Button size="xs" variant="light" onClick={onOpenCreate}>
            Create {labels.singular}
          </Button>
        </Group>
      </Group>

      {state.type === "LOADING" && <Loader size="sm" />}
      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      {state.type === "LOADED" && state.items.length === 0 && (
        <Alert color="yellow">No {labels.plural}.</Alert>
      )}
      {state.type === "LOADED" &&
        state.items.map((profile) => (
          <Paper key={profile.id} withBorder p="sm">
            <Stack gap="xs">
              <Group justify="space-between" align="flex-start">
                <Stack gap={2}>
                  <Group gap="xs">
                    <Text fw={600}>{profile.display_name}</Text>
                    <Badge variant="light">{labels.singular}</Badge>
                    <Badge
                      color={profile.compatible ? "green" : "red"}
                      variant="light"
                    >
                      {profile.compatible ? "Compatible" : "Incompatible"}
                    </Badge>
                    {profile.lifecycle === "disabled" && (
                      <Badge color="gray" variant="outline">
                        Disabled
                      </Badge>
                    )}
                    {profile.schema_version !== 1 && (
                      <Badge color="blue" variant="outline">
                        Schema v{profile.schema_version}
                      </Badge>
                    )}
                  </Group>
                  <Text size="xs" c="dimmed">
                    {profile.description || "No description"} · Version{" "}
                    {profile.version}
                  </Text>
                  {!profile.compatible && (
                    <Stack gap={2}>
                      <Text size="xs" c="red">
                        {compatibilityMessage(
                          profile.compatibility_reason_code,
                        )}
                      </Text>
                      {profile.compatibility_reason_code !== null && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          {profile.compatibility_reason_code}
                        </Text>
                      )}
                      {profile.missing_capabilities.length > 0 && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          Missing: {profile.missing_capabilities.join(", ")}
                        </Text>
                      )}
                    </Stack>
                  )}
                </Stack>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="subtle"
                    disabled={profile.spec === null}
                    onClick={() => onOpenEdit(profile)}
                  >
                    Edit
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    loading={submitting}
                    disabled={!profile.compatible}
                    onClick={() => onRecreate(profile)}
                  >
                    Recreate Runtimes
                  </Button>
                  <Button
                    size="xs"
                    color="red"
                    variant="subtle"
                    disabled={submitting}
                    onClick={() => onOpenDelete(profile)}
                  >
                    Delete
                  </Button>
                </Group>
              </Group>
            </Stack>
          </Paper>
        ))}

      {operationState.type === "LOADING" && <Loader size="sm" />}
      {operationState.type === "ERROR" && (
        <Alert color="red">{operationState.message}</Alert>
      )}
      {operationState.type === "LOADED" && (
        <Paper withBorder p="sm">
          <Stack gap="xs">
            <Group justify="space-between">
              <Text size="sm" fw={600}>
                {operationState.operation.target_kind === "provider"
                  ? "Provider recreation progress"
                  : `${labels.singular} recreation progress`}
              </Text>
              <Badge>{statusLabel(operationState.operation.status)}</Badge>
            </Group>
            <Progress
              value={
                operationState.operation.total_count === 0
                  ? 100
                  : ((operationState.operation.succeeded_count +
                      operationState.operation.skipped_count +
                      operationState.operation.failed_count) /
                      operationState.operation.total_count) *
                    100
              }
            />
            <Text size="xs" c="dimmed">
              {operationState.operation.succeeded_count} succeeded ·{" "}
              {operationState.operation.running_count} running ·{" "}
              {operationState.operation.failed_count} failed ·{" "}
              {operationState.operation.skipped_count} skipped
            </Text>
            <ScrollArea mah={rem(240)}>
              <Stack gap="xs">
                {operationState.operation.items.map((item) => (
                  <Alert
                    key={item.runtime_id}
                    color={item.status === "failed" ? "red" : "yellow"}
                    title={`${item.runtime_id} · ${statusLabel(item.status)}`}
                  >
                    <Stack gap={2}>
                      <Text size="sm">
                        {item.failure_message ?? "No additional detail."}
                      </Text>
                      {item.failure_code !== null && (
                        <Text size="xs" c="dimmed" ff="monospace">
                          {item.failure_code}
                        </Text>
                      )}
                    </Stack>
                  </Alert>
                ))}
              </Stack>
            </ScrollArea>
          </Stack>
        </Paper>
      )}

      {errorMessage !== null && editorState.type === "CLOSED" && (
        <Alert color="red">{errorMessage}</Alert>
      )}

      <InfrastructureProfileEditor
        kind={profileKind}
        editorState={editorState}
        submitting={submitting}
        errorMessage={errorMessage}
        onCloseEditor={onCloseEditor}
        onClose={onCloseEditor}
        onSubmit={onSubmit}
      />
      <InfrastructureProfileDeletionModal
        state={deletionState}
        onClose={onCloseDeletion}
        onRetryImpact={onRetryDeletionImpact}
        onPreviousReferences={onPreviousDeletionReferences}
        onNextReferences={onNextDeletionReferences}
        onConfirm={onConfirmDeletion}
      />
    </Stack>
  );
}
