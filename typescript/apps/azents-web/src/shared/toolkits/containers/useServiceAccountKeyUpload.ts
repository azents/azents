"use client";
import { useCallback } from "react";
import { parseJsonRecord } from "@/shared/lib/unknown-value";
import { getServiceAccountKey } from "../service-account-fields";
import type {
  ServiceAccountKeyUploadControl,
  ToolkitConfigFieldsInput,
} from "../types";
/** The owning container reads files; invalid or absent uploads retain current credentials. */
export function useServiceAccountKeyUpload(
  onCredentialsChange: ToolkitConfigFieldsInput["onCredentialsChange"],
): ServiceAccountKeyUploadControl {
  const onKeyFileUpload = useCallback(
    (file: File | null): void => {
      if (!file) {
        return;
      }
      const reader = new FileReader();
      reader.onload = (): void => {
        const text = reader.result;
        if (typeof text === "string") {
          const serviceAccountKey = getServiceAccountKey(parseJsonRecord(text));
          if (serviceAccountKey) {
            onCredentialsChange({ service_account_key: serviceAccountKey });
          }
        }
      };
      reader.readAsText(file);
    },
    [onCredentialsChange],
  );
  return { onKeyFileUpload };
}
