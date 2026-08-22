"use client";

import { Button, Space, Typography } from "antd";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getCurrentUser, type AccountUser } from "@/lib/auth-client";

const HIDDEN_PREFIXES = ["/admin", "/login", "/register", "/forgot-password", "/public"];

const items = [
  ["/workspace", "工作台"],
  ["/subjects", "主体与 GEO"],
  ["/assistant", "AI 助手"],
  ["/subscription", "订阅与额度"],
  ["/plan-applications", "套餐申请"],
] as const;

export function UserWorkspaceNavigation() {
  const pathname = usePathname();
  const hidden = HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  const [user, setUser] = useState<AccountUser | null>(null);

  useEffect(() => {
    let current = true;
    if (hidden) {
      return () => {
        current = false;
      };
    }
    void getCurrentUser()
      .then((value) => {
        if (current) setUser(value);
      })
      .catch(() => {
        if (current) setUser(null);
      });
    return () => {
      current = false;
    };
  }, [hidden, pathname]);

  if (hidden || !user) return null;

  return (
    <header className="workspace-navigation">
      <nav aria-label="用户工作台导航">
        <Space wrap>
          {items.map(([href, label]) => (
            <Button key={href} href={href} type={pathname === href ? "primary" : "text"}>
              {label}
            </Button>
          ))}
        </Space>
      </nav>
      <Typography.Text type="secondary">
        {user.tenant?.brand_name || "显问 GEO"} · {user.nickname}
      </Typography.Text>
    </header>
  );
}
