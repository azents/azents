"use client";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

const CODE_EXPIRY_SECONDS = 10 * 60;
export interface EmailCodeStepViewProps {
  error: {
    sentAt: number;
    error: string | null;
    isPending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["error"];
  isPending: {
    sentAt: number;
    error: string | null;
    isPending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["isPending"];
  onSubmit: {
    sentAt: number;
    error: string | null;
    isPending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["onSubmit"];
  onResend: {
    sentAt: number;
    error: string | null;
    isPending: boolean;
    onSubmit: (code: string) => void;
    onResend: () => void;
  }["onResend"];
  t: ReturnType<typeof useTranslations<"elevation">>;
  code: string;
  remainingSeconds: number;
  handleChange: (value: string) => void;
  handleComplete: (value: string) => void;
  isExpired: boolean;
}
export function useEmailCodeStepController({
  sentAt,
  error,
  isPending,
  onSubmit,
  onResend,
}: {
  sentAt: number;
  error: string | null;
  isPending: boolean;
  onSubmit: (code: string) => void;
  onResend: () => void;
}): EmailCodeStepViewProps {
  const t = useTranslations("elevation");
  const [code, setCode] = useState("");
  const [remainingSeconds, setRemainingSeconds] = useState(() => {
    const elapsed = Math.floor((Date.now() - sentAt) / 1000);
    return Math.max(0, CODE_EXPIRY_SECONDS - elapsed);
  });

  useEffect(() => {
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

  const handleChange = useCallback((value: string) => {
    setCode(value.toUpperCase());
  }, []);

  const handleComplete = useCallback(
    (value: string) => {
      onSubmit(value);
    },
    [onSubmit],
  );

  const isExpired = remainingSeconds === 0;
  return {
    error,
    isPending,
    onSubmit,
    onResend,
    t,
    code,
    remainingSeconds,
    handleChange,
    handleComplete,
    isExpired,
  };
}
