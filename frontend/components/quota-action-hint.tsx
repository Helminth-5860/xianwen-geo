"use client";

import { Typography } from "antd";
import { useEffect, useState } from "react";

import {
  CUSTOMER_QUOTA_PRESENTATION,
  formatQuotaAmount,
  getCurrentQuotaAccounts,
  normalizeCustomerQuotaAccounts,
  type CustomerQuotaType,
  type UserQuotaSummary,
} from "@/lib/quota-client";

export function QuotaActionHint({
  quotaType,
  actionText,
}: Readonly<{
  quotaType: CustomerQuotaType;
  actionText: string;
}>) {
  const [account, setAccount] = useState<UserQuotaSummary | null>(null);

  useEffect(() => {
    let active = true;
    void getCurrentQuotaAccounts()
      .then((result) => {
        if (!active) return;
        const found = normalizeCustomerQuotaAccounts(result.accounts).find(
          (item) => item.quota_type === quotaType,
        );
        setAccount(found ?? null);
      })
      .catch(() => {
        if (active) setAccount(null);
      });
    return () => {
      active = false;
    };
  }, [quotaType]);

  const presentation = CUSTOMER_QUOTA_PRESENTATION[quotaType];
  return (
    <Typography.Text type="secondary">
      {actionText}
      {account
        ? `，剩余 ${formatQuotaAmount(account.available, account.unlimited)} ${presentation.unit}`
        : ""}
    </Typography.Text>
  );
}
