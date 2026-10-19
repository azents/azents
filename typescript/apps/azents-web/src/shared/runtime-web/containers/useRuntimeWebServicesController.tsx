"use client";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import type { RuntimeWebDurationSeconds } from "../types";
import type { RuntimeWebServicesContainerOutput } from "./useRuntimeWebServicesContainer";
import type { RuntimeWebServiceResponse } from "@azents/public-client";
type RuntimeWebServicesProps = RuntimeWebServicesContainerOutput;

export interface RuntimeWebServicesViewProps {
  state: RuntimeWebServicesProps["state"];
  action: RuntimeWebServicesProps["action"];
  mutationError: RuntimeWebServicesProps["mutationError"];
  onTurnOn: RuntimeWebServicesProps["onTurnOn"];
  onTurnOff: RuntimeWebServicesProps["onTurnOff"];
  onReset: RuntimeWebServicesProps["onReset"];
  t: ReturnType<typeof useTranslations<"runtimeWeb">>;
  locale: string;
  createOpened: boolean;
  setCreateOpened: React.Dispatch<React.SetStateAction<boolean>>;
  port: string | number;
  setPort: React.Dispatch<React.SetStateAction<string | number>>;
  label: string;
  setLabel: React.Dispatch<React.SetStateAction<string>>;
  duration: RuntimeWebDurationSeconds;
  setDuration: React.Dispatch<React.SetStateAction<RuntimeWebDurationSeconds>>;
  turnOn: boolean;
  setTurnOn: React.Dispatch<React.SetStateAction<boolean>>;
  editing: RuntimeWebServiceResponse | null;
  setEditing: React.Dispatch<
    React.SetStateAction<RuntimeWebServiceResponse | null>
  >;
  editLabel: string;
  setEditLabel: React.Dispatch<React.SetStateAction<string>>;
  editDuration: RuntimeWebDurationSeconds;
  setEditDuration: React.Dispatch<
    React.SetStateAction<RuntimeWebDurationSeconds>
  >;
  deleting: RuntimeWebServiceResponse | null;
  setDeleting: React.Dispatch<
    React.SetStateAction<RuntimeWebServiceResponse | null>
  >;
  submitServiceAction1: () => void;
  submitServiceAction2: (service: RuntimeWebServiceResponse) => void;
  submitServiceAction3: (service: RuntimeWebServiceResponse) => void;
}
export function useRuntimeWebServicesController({
  state,
  action,
  mutationError,
  onCreate,
  onUpdate,
  onTurnOn,
  onTurnOff,
  onReset,
  onDelete,
}: RuntimeWebServicesProps): RuntimeWebServicesViewProps {
  const t = useTranslations("runtimeWeb");
  const locale = useLocale();
  const [createOpened, setCreateOpened] = useState(false);
  const [port, setPort] = useState<number | string>(3000);
  const [label, setLabel] = useState("");
  const [duration, setDuration] = useState<RuntimeWebDurationSeconds>(3600);
  const [turnOn, setTurnOn] = useState(false);
  const [editing, setEditing] = useState<RuntimeWebServiceResponse | null>(
    null,
  );
  const [editLabel, setEditLabel] = useState("");
  const [editDuration, setEditDuration] =
    useState<RuntimeWebDurationSeconds>(3600);
  const [deleting, setDeleting] = useState<RuntimeWebServiceResponse | null>(
    null,
  );
  const submittedAction = useRef<"create" | "update" | "delete" | null>(null);

  useEffect(() => {
    if (action !== null || mutationError !== null) {
      return;
    }
    if (submittedAction.current === "create") {
      setCreateOpened(false);
      setPort(3000);
      setLabel("");
      setDuration(3600);
      setTurnOn(false);
    } else if (submittedAction.current === "update") {
      setEditing(null);
    } else if (submittedAction.current === "delete") {
      setDeleting(null);
    }
    submittedAction.current = null;
  }, [action, mutationError]);

  function submitServiceAction1(): void {
    if (typeof port !== "number") {
      return;
    }
    submittedAction.current = "create";
    onCreate({
      port,
      label: label.trim() || null,
      selectedDurationSeconds: duration,
      turnOn,
    });
  }

  function submitServiceAction2(service: RuntimeWebServiceResponse): void {
    submittedAction.current = "update";
    onUpdate(service, {
      label: editLabel.trim() || null,
      selectedDurationSeconds: editDuration,
    });
  }

  function submitServiceAction3(service: RuntimeWebServiceResponse): void {
    submittedAction.current = "delete";
    onDelete(service);
  }
  return {
    state,
    action,
    mutationError,
    onTurnOn,
    onTurnOff,
    onReset,
    t,
    locale,
    createOpened,
    setCreateOpened,
    port,
    setPort,
    label,
    setLabel,
    duration,
    setDuration,
    turnOn,
    setTurnOn,
    editing,
    setEditing,
    editLabel,
    setEditLabel,
    editDuration,
    setEditDuration,
    deleting,
    setDeleting,
    submitServiceAction1,
    submitServiceAction2,
    submitServiceAction3,
  };
}
