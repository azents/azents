"use client";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

const CODE_EXPIRY_SECONDS = 10 * 60;
export interface VerifyStepFormViewProps {
  email: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["email"];
  error: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["error"];
  isPending: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["isPending"];
  isResending: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["isResending"];
  onSubmit: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["onSubmit"];
  onResend: {
    email: string;
    sentAt: number;
    error: string | null;
    isPending: boolean;
    isResending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["onResend"];
  t: ReturnType<typeof useTranslations<"auth">>;
  code: string;
  remainingSeconds: number;
  inputType: RegExp;
  handleChange: (value: string) => void;
  handlePaste: (e: React.ClipboardEvent) => void;
  handleSubmit: (e: React.FormEvent) => void;
  handleComplete: (value: string) => void;
  isExpired: boolean;
}
export function useVerifyStepFormController({
  email,
  sentAt,
  error,
  isPending,
  isResending,
  onSubmit,
  onResend,
}: {
  email: string;
  sentAt: number;
  error: string | null;
  isPending: boolean;
  isResending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): VerifyStepFormViewProps {
  const t = useTranslations("auth");
  const [code, setCode] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(() => {
    if (!sentAt) {
      return 0;
    }
    const elapsed = Math.floor((Date.now() - sentAt) / 1000);
    return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
  });

  /** Recalculate timer + reset code when sentAt changes */
  useEffect(() => {
    if (!sentAt) {
      return;
    }

    const calcRemaining = (): number => {
      const elapsed = Math.floor((Date.now() - sentAt) / 1000);
      return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
    };

    setRemainingSeconds(calcRemaining());
    setCode("");

    const timer = setInterval(() => {
      const remaining = calcRemaining();
      setRemainingSeconds(remaining);
      if (remaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [sentAt]);

  const inputType = /^[A-Za-z0-9]*$/;

  const handleChange = useCallback((value: string) => {
    setCode(value.toUpperCase());
  }, []);

  const handlePaste = useCallback((e: React.ClipboardEvent) => {
    const pasted = e.clipboardData
      .getData("text")
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "")
      .slice(0, 6);
    if (pasted.length > 0) {
      e.preventDefault();
      setCode(pasted);
    }
  }, []);

  function handleSubmit(e: React.FormEvent): void {
    e.preventDefault();
    if (code.length === 6) {
      onSubmit(code);
    }
  }

  function handleComplete(value: string): void {
    onSubmit(value);
  }

  const isExpired = remainingSeconds === 0;
  return {
    email,
    error,
    isPending,
    isResending,
    onSubmit,
    onResend,
    t,
    code,
    remainingSeconds,
    inputType,
    handleChange,
    handlePaste,
    handleSubmit,
    handleComplete,
    isExpired,
  };
}
