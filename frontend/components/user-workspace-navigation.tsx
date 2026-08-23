"use client";

import { AppstoreOutlined, FileSearchOutlined, FundProjectionScreenOutlined, RobotOutlined, SettingOutlined, TagsOutlined } from "@ant-design/icons";
import { Button, Typography } from "antd";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getCurrentUser, type AccountUser } from "@/lib/auth-client";

const HIDDEN_PREFIXES = ["/admin", "/login", "/register", "/forgot-password", "/public"];

const items = [
  ["/workspace", "GEO 总览", AppstoreOutlined],
  ["/subjects", "主体管理", SettingOutlined],
  ["/subjects", "问题与关键词库", TagsOutlined],
  ["/subjects", "AI 可见度检测", FileSearchOutlined],
  ["/subjects", "GEO 报告与洞察", FundProjectionScreenOutlined],
  ["/assistant", "显问 AI 助手", RobotOutlined],
] as const;

export function UserWorkspaceNavigation() {
  const pathname = usePathname();
  const hidden = HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  const [user, setUser] = useState<AccountUser | null>(null);

  useEffect(() => {
    if (hidden) return;
    void getCurrentUser().then(setUser).catch(() => setUser(null));
  }, [hidden]);

  if (hidden || !user) return null;

  return (
    <aside className="geo-sidebar">
      <div className="geo-sidebar__brand">显问 GEO</div>
      <nav aria-label="GEO 工作台导航">
        {items.map(([href, label, Icon]) => (
          <Button key={label} href={href} type={pathname === href ? "primary" : "text"}>
            <Icon />
            {label}
          </Button>
        ))}
      </nav>
      <Typography.Text type="secondary" className="geo-sidebar__user">
        {user.tenant?.brand_name || "显问 GEO"}
      </Typography.Text>
    </aside>
  );
}
