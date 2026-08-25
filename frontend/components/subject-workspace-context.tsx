"use client";

import { Button, Modal, Select, Space, Spin, Typography, message } from "antd";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { getCurrentUser, type AccountUser } from "@/lib/auth-client";
import {
  getSubjects,
  navigateWorkspaceAfterSubjectChange,
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

type SwitchGuard = Readonly<{
  isDirty: () => boolean;
  save: () => Promise<boolean>;
}>;

type SubjectWorkspaceValue = Readonly<{
  active: boolean;
  loading: boolean;
  user: AccountUser | null;
  subjects: SubjectSummary[];
  subjectContext: SubjectContext;
  currentSubject: SubjectSummary | null;
  switchingSubject: boolean;
  requestSubjectSwitch: (subjectId: string) => void;
  registerSwitchGuard: (key: string, guard: SwitchGuard) => () => void;
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
  switchingSubject: false,
  requestSubjectSwitch: () => undefined,
  registerSwitchGuard: () => () => undefined,
  refresh: async () => undefined,
};
const SubjectWorkspaceContext = createContext<SubjectWorkspaceValue>(fallbackWorkspaceValue);

export function isWorkspaceShellHiddenPath(pathname: string) {
  return HIDDEN_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export function SubjectWorkspaceProvider({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();
  const hidden = isWorkspaceShellHiddenPath(pathname);
  const [messageApi, messageHolder] = message.useMessage();
  const [user, setUser] = useState<AccountUser | null>(null);
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [subjectContext, setSubjectContext] = useState<SubjectContext>(emptyContext);
  const [loading, setLoading] = useState(!hidden);
  const [switchingSubject, setSwitchingSubject] = useState(false);
  const [pendingSubjectId, setPendingSubjectId] = useState<string | null>(null);
  const [savingBeforeSwitch, setSavingBeforeSwitch] = useState(false);
  const guards = useRef(new Map<string, SwitchGuard>());

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
      setSubjects(data.subjects.filter((subject) => subject.current_version_no !== null));
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
    () =>
      subjects.find((subject) => subject.id === subjectContext.current_subject_id) ??
      subjects.find((subject) => subject.is_current) ??
      (subjects.length === 1 ? subjects[0] : null),
    [subjectContext.current_subject_id, subjects],
  );

  const registerSwitchGuard = useCallback((key: string, guard: SwitchGuard) => {
    guards.current.set(key, guard);
    return () => guards.current.delete(key);
  }, []);

  const performSwitch = useCallback(
    async (subjectId: string) => {
      if (subjectId === currentSubject?.id) return;
      setSwitchingSubject(true);
      try {
        await setCurrentSubject(subjectId, subjectContext.version);
        navigateWorkspaceAfterSubjectChange(pathname, subjectId);
      } catch {
        setSwitchingSubject(false);
        setPendingSubjectId(null);
        messageApi.error("主体切换失败，请刷新页面后重试");
        await refresh();
      }
    },
    [currentSubject?.id, messageApi, pathname, refresh, subjectContext.version],
  );

  const requestSubjectSwitch = useCallback(
    (subjectId: string) => {
      if (subjectId === currentSubject?.id || switchingSubject) return;
      const hasDirtyState = Array.from(guards.current.values()).some((guard) => guard.isDirty());
      if (hasDirtyState) {
        setPendingSubjectId(subjectId);
        return;
      }
      void performSwitch(subjectId);
    },
    [currentSubject?.id, performSwitch, switchingSubject],
  );

  const saveAndSwitch = async () => {
    if (!pendingSubjectId) return;
    setSavingBeforeSwitch(true);
    try {
      const dirtyGuards = Array.from(guards.current.values()).filter((guard) => guard.isDirty());
      for (const guard of dirtyGuards) {
        if (!(await guard.save())) {
          messageApi.error("当前页面保存失败，已取消主体切换");
          return;
        }
      }
      const target = pendingSubjectId;
      setPendingSubjectId(null);
      await performSwitch(target);
    } finally {
      setSavingBeforeSwitch(false);
    }
  };

  const value = useMemo<SubjectWorkspaceValue>(
    () => ({
      active: !hidden && user?.commercial_identity === "USER",
      loading,
      user,
      subjects,
      subjectContext,
      currentSubject,
      switchingSubject,
      requestSubjectSwitch,
      registerSwitchGuard,
      refresh,
    }),
    [
      currentSubject,
      hidden,
      loading,
      refresh,
      registerSwitchGuard,
      requestSubjectSwitch,
      subjectContext,
      subjects,
      switchingSubject,
      user,
    ],
  );

  return (
    <SubjectWorkspaceContext.Provider value={value}>
      {messageHolder}
      {children}
      <Modal
        title="当前页面有未保存修改"
        open={pendingSubjectId !== null}
        closable={!savingBeforeSwitch}
        mask={{ closable: false }}
        footer={
          <Space wrap>
            <Button disabled={savingBeforeSwitch} onClick={() => setPendingSubjectId(null)}>
              取消切换
            </Button>
            <Button
              disabled={savingBeforeSwitch}
              onClick={() => {
                const target = pendingSubjectId;
                setPendingSubjectId(null);
                if (target) void performSwitch(target);
              }}
            >
              放弃修改并切换
            </Button>
            <Button
              type="primary"
              loading={savingBeforeSwitch}
              onClick={() => void saveAndSwitch()}
            >
              保存后切换
            </Button>
          </Space>
        }
        onCancel={() => setPendingSubjectId(null)}
      >
        <Typography.Paragraph>
          切换主体会清空当前页面的临时状态。你可以先保存修改，也可以放弃修改后切换。
        </Typography.Paragraph>
      </Modal>
    </SubjectWorkspaceContext.Provider>
  );
}

export function useSubjectWorkspace() {
  return useContext(SubjectWorkspaceContext);
}

export function useSubjectSwitchGuard(key: string, dirty: boolean, save: () => Promise<boolean>) {
  const { registerSwitchGuard } = useSubjectWorkspace();
  useEffect(
    () =>
      registerSwitchGuard(key, {
        isDirty: () => dirty,
        save,
      }),
    [dirty, key, registerSwitchGuard, save],
  );
}

export function SubjectWorkspaceTopbar() {
  const { active, currentSubject, loading, requestSubjectSwitch, subjects, switchingSubject } =
    useSubjectWorkspace();
  if (!active) return null;

  return (
    <header className="subject-workspace-topbar">
      <Space size="middle" wrap>
        <Typography.Text type="secondary">当前主体</Typography.Text>
        {loading ? (
          <Spin size="small" />
        ) : subjects.length ? (
          <Select
            aria-label="Workspace 当前主体"
            value={currentSubject?.id}
            loading={switchingSubject}
            disabled={switchingSubject || subjects.length === 1}
            options={subjects.map((subject) => ({
              value: subject.id,
              label: subject.official_name || subject.subject_type.name,
            }))}
            onChange={requestSubjectSwitch}
          />
        ) : (
          <Typography.Text strong>尚未创建可用主体</Typography.Text>
        )}
      </Space>
      <Button href={currentSubject ? `/subjects/${currentSubject.id}` : "/subjects"}>
        {currentSubject ? "查看主体资料" : "创建主体"}
      </Button>
    </header>
  );
}
