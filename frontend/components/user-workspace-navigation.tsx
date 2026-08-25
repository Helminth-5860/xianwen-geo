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
import { Button, Divider, Select, Typography } from "antd";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getCurrentUser, type AccountUser } from "@/lib/auth-client";
import {
  getSubjects,
  reloadWorkspaceAfterSubjectChange,
  SUBJECT_CONTEXT_UPDATED_EVENT,
  setCurrentSubject,
  type SubjectContext,
  type SubjectSummary,
} from "@/lib/subjects-client";

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
    label: "主体档案",
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
  const hidden = HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  const [user, setUser] = useState<AccountUser | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectContext, setSubjectContext] = useState<SubjectContext>({
    current_subject_id: null,
    version: 0,
  });
  const [currentSubjectId, setCurrentSubjectId] = useState<string | null>(null);
  const [currentSubjectName, setCurrentSubjectName] = useState("");
  const [switchingSubject, setSwitchingSubject] = useState(false);

  useEffect(() => {
    let current = true;
    if (hidden) return () => undefined;

    const loadNavigation = () =>
      getCurrentUser()
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
            setSubjects(data.subjects);
            setSubjectContext(data.context);
            setCurrentSubjectId(subject?.id ?? null);
            setCurrentSubjectName(subject?.official_name || subject?.subject_type.name || "");
          } catch {
            if (current) {
              setSubjects([]);
              setSubjectContext({ current_subject_id: null, version: 0 });
              setCurrentSubjectId(null);
              setCurrentSubjectName("");
            }
          }
        })
        .catch(() => {
          if (current) setUser(null);
        });

    void loadNavigation();
    window.addEventListener(SUBJECT_CONTEXT_UPDATED_EVENT, loadNavigation);

    return () => {
      current = false;
      window.removeEventListener(SUBJECT_CONTEXT_UPDATED_EVENT, loadNavigation);
    };
  }, [hidden]);

  if (hidden || !user || user.commercial_identity !== "USER") return null;

  return (
    <aside className="geo-sidebar">
      <div className="geo-sidebar__brand">
        <span className="geo-sidebar__brand-mark">显问</span>
        <Typography.Text type="secondary">GEO</Typography.Text>
      </div>

      <div className="geo-sidebar__subject">
        <Typography.Text type="secondary">当前主体</Typography.Text>
        {subjects.some((subject) => subject.current_version_no !== null) ? (
          <Select
            aria-label="当前主体"
            value={currentSubjectId ?? undefined}
            loading={switchingSubject}
            disabled={switchingSubject}
            placeholder="请选择主体"
            options={subjects
              .filter((subject) => subject.current_version_no !== null)
              .map((subject) => ({
                value: subject.id,
                label: subject.official_name || subject.subject_type.name,
              }))}
            onChange={(subjectId) => {
              setSwitchingSubject(true);
              void setCurrentSubject(subjectId, subjectContext.version)
                .then(reloadWorkspaceAfterSubjectChange)
                .catch(() => setSwitchingSubject(false));
            }}
          />
        ) : (
          <Typography.Text strong ellipsis={{ tooltip: currentSubjectName || "尚未选择主体" }}>
            {currentSubjectName || "尚未选择主体"}
          </Typography.Text>
        )}
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
