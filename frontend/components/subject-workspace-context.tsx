"use client";

import { Space, Spin, Typography } from "antd";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { AccountMenu } from "@/components/account/account-menu";
import { getCurrentUser, type AccountUser } from "@/lib/auth-client";
import {
  getSubjects,
  SUBJECT_CONTEXT_UPDATED_EVENT,
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

type SubjectWorkspaceValue = Readonly<{
  active: boolean;
  loading: boolean;
  user: AccountUser | null;
  subjects: SubjectSummary[];
  subjectContext: SubjectContext;
  currentSubject: SubjectSummary | null;
  refresh: () => Promise<void>;
}>;

const emptyContext: SubjectContext = { current_subject_id: null, version: 0 };
const fallbackWorkspaceValue: SubjectWorkspaceValue = {
  active: false,
  loading: false,
  user: null,
  subjects: [],
  subjectContext: emptyContext,
  currentSubject: null,
  refresh: async () => undefined,
};
const SubjectWorkspaceContext = createContext<SubjectWorkspaceValue>(fallbackWorkspaceValue);

export function isWorkspaceShellHiddenPath(pathname: string) {
  return HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export function SubjectWorkspaceProvider({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const hidden = isWorkspaceShellHiddenPath(pathname);
  const [user, setUser] = useState<AccountUser | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectContext, setSubjectContext] = useState<SubjectContext>(emptyContext);
  const [loading, setLoading] = useState(!hidden);

  const refresh = useCallback(async () => {
    if (hidden) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const account = await getCurrentUser();
      setUser(account);
      if (account.commercial_identity !== "USER") {
        setSubjects([]);
        setSubjectContext(emptyContext);
        return;
      }
      const data = await getSubjects();
      setSubjects(
        data.subjects.filter(
          (subject) => subject.status === "active" && subject.current_version_no !== null,
        ),
      );
      setSubjectContext(data.context);
    } catch {
      setUser(null);
      setSubjects([]);
      setSubjectContext(emptyContext);
    } finally {
      setLoading(false);
    }
  }, [hidden]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    window.addEventListener(SUBJECT_CONTEXT_UPDATED_EVENT, refresh);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(SUBJECT_CONTEXT_UPDATED_EVENT, refresh);
    };
  }, [refresh]);

  const currentSubject = useMemo(
    () => subjects.find((subject) => subject.status === "active") ?? null,
    [subjects],
  );

  const value = useMemo<SubjectWorkspaceValue>(
    () => ({
      active: !hidden && user?.commercial_identity === "USER",
      loading,
      user,
      subjects,
      subjectContext,
      currentSubject,
      refresh,
    }),
    [currentSubject, hidden, loading, refresh, subjectContext, subjects, user],
  );

  return (
    <SubjectWorkspaceContext.Provider value={value}>{children}</SubjectWorkspaceContext.Provider>
  );
}

export function useSubjectWorkspace() {
  return useContext(SubjectWorkspaceContext);
}

export function useSubjectSwitchGuard(key: string, dirty: boolean, save: () => Promise<boolean>) {
  void key;
  void dirty;
  void save;
  // 单主体模式下不存在主体切换；保留兼容入口，避免影响既有编辑页的未保存状态处理。
}

export function SubjectWorkspaceSwitcher({
  className,
  stacked = false,
}: Readonly<{ className?: string; stacked?: boolean }>) {
  const { active, currentSubject, loading } = useSubjectWorkspace();
  if (!active) return null;

  return (
    <div
      className={[
        "subject-workspace-switcher",
        stacked && "subject-workspace-switcher--stacked",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Space size={stacked ? 6 : "middle"} orientation={stacked ? "vertical" : "horizontal"}>
        <Typography.Text type="secondary">主体</Typography.Text>
        {loading ? (
          <Spin size="small" />
        ) : (
          <Typography.Text strong>
            {currentSubject?.official_name || currentSubject?.subject_type.name || "请先绑定主体"}
          </Typography.Text>
        )}
      </Space>
    </div>
  );
}

export function SubjectWorkspaceTopbar({
  navigationTrigger,
  focusControl,
}: Readonly<{
  navigationTrigger?: ReactNode;
  focusControl?: ReactNode;
}>) {
  const { active, user } = useSubjectWorkspace();
  if (!active) return null;

  return (
    <header className="subject-workspace-topbar">
      <div className="subject-workspace-topbar__leading">
        {navigationTrigger}
        <span className="subject-workspace-topbar__mobile-brand">显问 GEO</span>
        <SubjectWorkspaceSwitcher className="subject-workspace-topbar__subject" />
      </div>
      <Space size="small" className="subject-workspace-topbar__actions">
        {focusControl}
        {user ? <AccountMenu user={user} /> : null}
      </Space>
    </header>
  );
}
