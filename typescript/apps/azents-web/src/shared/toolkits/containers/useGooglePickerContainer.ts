"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { loadGooglePicker, openGooglePicker } from "../google-picker";
import type { GooglePickerHandle } from "../google-picker";
import type { GooglePickerState } from "../google-types";
import type { GooglePickerTokenOutput } from "@azents/public-client";

interface Options {
  enabled: boolean;
  contextKey: string;
  issue: () => Promise<GooglePickerTokenOutput>;
  unavailableMessage: string;
  expiredMessage: string;
}
interface Result {
  picker: GooglePickerState;
  onOpenPicker: () => Promise<void>;
  onClosePicker: () => void;
}
export function useGooglePickerContainer(options: Options): Result {
  const [picker, setPicker] = useState<GooglePickerState>({ type: "IDLE" });
  const handle = useRef<GooglePickerHandle | null>(null);
  const generation = useRef(0);
  const opening = useRef(false);
  const clear = useCallback((): void => {
    handle.current?.close();
    handle.current = null;
  }, []);
  useEffect(() => {
    setPicker({ type: "IDLE" });
    return () => {
      generation.current += 1;
      opening.current = false;
      clear();
    };
  }, [options.contextKey, options.enabled, clear]);
  const open = async (): Promise<void> => {
    if (!options.enabled || opening.current) {
      return;
    }
    clear();
    opening.current = true;
    const operation = ++generation.current;
    setPicker({ type: "LOADING" });
    try {
      const api = await loadGooglePicker();
      if (generation.current !== operation) {
        return;
      }
      const receipt = await options.issue();
      if (generation.current !== operation) {
        return;
      }
      handle.current = openGooglePicker(api, receipt, (result) => {
        handle.current = null;
        opening.current = false;
        if (generation.current !== operation) {
          return;
        }
        setPicker(
          result.type === "EXPIRED"
            ? { type: "ERROR", message: options.expiredMessage }
            : result,
        );
      });
      setPicker({ type: "OPEN" });
    } catch {
      if (generation.current === operation) {
        opening.current = false;
        clear();
        setPicker({ type: "ERROR", message: options.unavailableMessage });
      }
    }
  };
  return {
    picker,
    onOpenPicker: open,
    onClosePicker: () => {
      generation.current += 1;
      opening.current = false;
      clear();
      setPicker({ type: "CANCELLED" });
    },
  };
}
