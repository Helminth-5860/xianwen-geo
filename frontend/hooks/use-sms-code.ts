"use client";

import { useCallback, useEffect, useState } from "react";

import { sendSms, type SmsPurpose } from "@/lib/auth-client";

export function useSmsCode(purpose: SmsPurpose) {
  const [sending, setSending] = useState(false);
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    if (remaining <= 0) return;
    const timer = window.setTimeout(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [remaining]);

  const send = useCallback(
    async (phone: string) => {
      if (sending || remaining > 0) return;
      setSending(true);
      try {
        const result = await sendSms(phone, purpose);
        setRemaining(result.resend_after);
      } finally {
        setSending(false);
      }
    },
    [purpose, remaining, sending],
  );

  return { send, sending, remaining, disabled: sending || remaining > 0 } as const;
}
