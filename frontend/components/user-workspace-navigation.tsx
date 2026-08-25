"use client";

import {
  AreaChartOutlined,
  BarChartOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
  RadarChartOutlined,
  SettingOutlined,
  SyncOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Button, Divider, Typography } from "antd";
import { usePathname } from "next/navigation";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";

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
    label: "主体档案",
    href: "/subjects",
    icon: SettingOutlined,
    active: (pathname) =>
      pathname.startsWith("/subjects") &&
      !pathname.includes("/keywords") &&
      !pathname.includes("/articles"),
  },
  {
    label: "关键词中心",
    href: (subjectId) => (subjectId ? `/subjects/${subjectId}/keywords` : "/subjects"),
    icon: TagsOutlined,
    active: (pathname) => pathname.includes("/keywords"),
  },
  {
    label: "问题库",
    href: (subjectId) => (subjectId ? `/subjects/${subjectId}/questions` : "/subjects"),
    icon: TagsOutlined,
    active: (pathname) => pathname.includes("/questions"),
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
    active: (pathname) =>
      pathname.startsWith("/geo/reports") &&
      !pathname.includes("/strategy") &&
      !pathname.startsWith("/geo/retest"),
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
  {
    label: "复测验证",
    href: "/geo/retest",
    icon: SyncOutlined,
    active: (pathname) => pathname.startsWith("/geo/retest"),
  },
];

export function UserWorkspaceNavigation() {
  const pathname = usePathname();
  const { active, currentSubject, user } = useSubjectWorkspace();
  if (!active || !user) return null;
  const currentSubjectId = currentSubject?.id ?? null;
  const currentSubjectName =
    currentSubject?.official_name || currentSubject?.subject_type.name || "尚未选择主体";

  return (
    <aside className="geo-sidebar">
      <div className="geo-sidebar__brand">
        <span className="geo-sidebar__brand-mark">显问</span>
        <Typography.Text type="secondary">GEO</Typography.Text>
      </div>

      <div className="geo-sidebar__subject">
        <Typography.Text type="secondary">当前主体</Typography.Text>
        <Typography.Text strong ellipsis={{ tooltip: currentSubjectName }}>
          {currentSubjectName}
        </Typography.Text>
      </div>

      <nav aria-label="GEO 工作台导航">
        {workflowItems.map((item) => {
          const href = typeof item.href === "function" ? item.href(currentSubjectId) : item.href;
          const Icon = item.icon;
          return (
            <Button
              key={item.label}
              aria-label={item.label}
              href={href}
              type={item.active(pathname) ? "primary" : "text"}
            >
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
