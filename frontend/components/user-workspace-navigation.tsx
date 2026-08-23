"use client";

import {
  AreaChartOutlined,
  BarChartOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
  RadarChartOutlined,
  SettingOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Button, Divider, Typography } from "antd";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getCurrentUser, type AccountUser } from "@/lib/auth-client";
import { getSubjects } from "@/lib/subjects-client";

const HIDDEN_PREFIXES = [
  "/admin",
  "/assistant",
  "/login",
  "/register",
  "/forgot-password",
  "/public",
];

type NavItem = Readonly<{
  label: string;
  href: string | ((subjectId: string | null) => string);
  icon: typeof AreaChartOutlined;
  active: (pathname: string) => boolean;
}>;

const workflowItems: NavItem[] = [
  {
    label: "GEO 总览",
    href: "/workspace",
    icon: AreaChartOutlined,
    active: (pathname) => pathname === "/workspace",
  },
  {
    label: "主体与知识",
    href: "/subjects",
    icon: SettingOutlined,
    active: (pathname) =>
      pathname.startsWith("/subjects") &&
      !pathname.includes("/keywords") &&
      !pathname.includes("/articles"),
  },
  {
    label: "关键词与问题",
    href: (subjectId) => (subjectId ? `/subjects/${subjectId}/keywords` : "/subjects"),
    icon: TagsOutlined,
    active: (pathname) => pathname.includes("/keywords"),
  },
  {
    label: "AI 可见度检测",
    href: "/geo/detections",
    icon: RadarChartOutlined,
    active: (pathname) => pathname.startsWith("/geo/detections"),
  },
  {
    label: "GEO 报告与洞察",
    href: "/geo/reports",
    icon: BarChartOutlined,
    active: (pathname) => pathname.startsWith("/geo/reports") && !pathname.includes("/strategy"),
  },
  {
    label: "优化策略",
    href: "/geo/strategy",
    icon: FundProjectionScreenOutlined,
    active: (pathname) => pathname.startsWith("/geo/strategy") || pathname.includes("/strategy"),
  },
  {
    label: "内容执行",
    href: (subjectId) => (subjectId ? `/subjects/${subjectId}/articles/new` : "/subjects"),
    icon: FileTextOutlined,
    active: (pathname) => pathname.includes("/articles"),
  },
];

export function UserWorkspaceNavigation() {
  const pathname = usePathname();
  const hidden = HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  const [user, setUser] = useState<AccountUser | null>(null);
  const [currentSubjectId, setCurrentSubjectId] = useState<string | null>(null);
  const [currentSubjectName, setCurrentSubjectName] = useState("");

  useEffect(() => {
    let current = true;
    if (hidden) return () => undefined;

    void getCurrentUser()
      .then(async (value) => {
        if (!current) return;
        setUser(value);
        try {
          const data = await getSubjects();
          if (!current) return;
          const subject =
            data.subjects.find((item) => item.id === data.context.current_subject_id) ??
            data.subjects.find((item) => item.is_current) ??
            null;
          setCurrentSubjectId(subject?.id ?? null);
          setCurrentSubjectName(subject?.official_name || "");
        } catch {
          if (current) {
            setCurrentSubjectId(null);
            setCurrentSubjectName("");
          }
        }
      })
      .catch(() => {
        if (current) setUser(null);
      });

    return () => {
      current = false;
    };
  }, [hidden]);

  if (hidden || !user) return null;

  return (
    <aside className="geo-sidebar">
      <div className="geo-sidebar__brand">
        <span className="geo-sidebar__brand-mark">显问</span>
        <Typography.Text type="secondary">GEO</Typography.Text>
      </div>

      <div className="geo-sidebar__subject">
        <Typography.Text type="secondary">当前主体</Typography.Text>
        <Typography.Text strong ellipsis={{ tooltip: currentSubjectName || "尚未选择主体" }}>
          {currentSubjectName || "尚未选择主体"}
        </Typography.Text>
      </div>

      <nav aria-label="GEO 工作台导航">
        {workflowItems.map((item) => {
          const href = typeof item.href === "function" ? item.href(currentSubjectId) : item.href;
          const Icon = item.icon;
          return (
            <Button key={item.label} href={href} type={item.active(pathname) ? "primary" : "text"}>
              <Icon />
              {item.label}
            </Button>
          );
        })}
      </nav>

      <div className="geo-sidebar__footer">
        <Divider />
        <Button type="text" href="/subscription" block>
          套餐与额度
        </Button>
        <Typography.Text type="secondary" className="geo-sidebar__tenant">
          {user.tenant?.brand_name || "显问 GEO"}
        </Typography.Text>
      </div>
    </aside>
  );
}
