"use client";

import {
  ApiOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  CreditCardOutlined,
  DatabaseOutlined,
  HistoryOutlined,
  MenuOutlined,
  SettingOutlined,
  ShopOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Divider, Drawer, Dropdown, Menu, Space, Tag, Typography } from "antd";
import type { ItemType } from "antd/es/menu/interface";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";

import type { AdminContext } from "@/lib/admin-rbac-client";
import { logoutAdmin } from "@/lib/admin-rbac-client";

type ConsoleRoute = Readonly<{
  href: string;
  label: string;
  icon: ReactNode;
  menuKeys?: string[];
  superOnly?: boolean;
}>;

const routes: ConsoleRoute[] = [
  { href: "/admin", label: "平台总览", icon: <AppstoreOutlined /> },
  {
    href: "/admin/admins",
    label: "管理员",
    icon: <TeamOutlined />,
    menuKeys: ["menu.admin.admins"],
  },
  {
    href: "/admin/users",
    label: "用户",
    icon: <UserOutlined />,
    menuKeys: ["menu.admin.users"],
  },
  {
    href: "/admin/plans",
    label: "套餐管理",
    icon: <CreditCardOutlined />,
    menuKeys: ["menu.admin.plans", "menu.admin.subscriptions", "menu.admin.plan-applications"],
  },
  {
    href: "/admin/quotas",
    label: "额度管理",
    icon: <BarChartOutlined />,
    menuKeys: ["menu.admin.quotas"],
  },
  {
    href: "/admin/models",
    label: "模型与接口",
    icon: <ApiOutlined />,
    menuKeys: ["menu.admin.models"],
  },
  {
    href: "/admin/business-data",
    label: "业务数据",
    icon: <DatabaseOutlined />,
    menuKeys: ["menu.admin.operations", "menu.admin.users"],
  },
  {
    href: "/admin/paid-media-inquiries",
    label: "媒体发布需求",
    icon: <ShopOutlined />,
    menuKeys: ["menu.admin.operations"],
  },
  {
    href: "/admin/system-status",
    label: "系统状态",
    icon: <BellOutlined />,
    menuKeys: ["menu.admin.operations"],
    superOnly: true,
  },
  {
    href: "/admin/operation-records",
    label: "操作记录",
    icon: <HistoryOutlined />,
    menuKeys: ["menu.admin.audit"],
  },
  {
    href: "/admin/settings",
    label: "系统设置",
    icon: <SettingOutlined />,
    superOnly: true,
  },
];

const titleForPath = (pathname: string) => {
  const match = [...routes]
    .sort((left, right) => right.href.length - left.href.length)
    .find((route) => pathname === route.href || pathname.startsWith(`${route.href}/`));
  return match?.label ?? "后台管理";
};

const canSee = (route: ConsoleRoute, context: AdminContext) => {
  if (context.commercial_identity === "SUPER_ADMIN") return true;
  if (route.superOnly) return false;
  if (route.href === "/admin") return true;
  return route.menuKeys?.some((key) => context.menu_keys.includes(key)) ?? false;
};

function ConsoleMenu({ context, pathname }: { context: AdminContext; pathname: string }) {
  const items = useMemo<ItemType[]>(() => {
    const visible = routes.filter((route) => canSee(route, context));
    const item = (route: ConsoleRoute): ItemType => ({
      key: route.href,
      icon: route.icon,
      label: <Link href={route.href}>{route.label}</Link>,
    });
    const dashboard = visible.find((route) => route.href === "/admin");
    const userItems = visible.filter((route) =>
      ["/admin/admins", "/admin/users"].includes(route.href),
    );
    const remaining = visible.filter(
      (route) => !["/admin", "/admin/admins", "/admin/users"].includes(route.href),
    );
    return [
      ...(dashboard ? [item(dashboard)] : []),
      ...(userItems.length
        ? [
            {
              key: "user-management",
              icon: <TeamOutlined />,
              label: "用户管理",
              children: userItems.map(item),
            },
          ]
        : []),
      ...remaining.map(item),
    ];
  }, [context]);

  const selected = [...routes]
    .sort((left, right) => right.href.length - left.href.length)
    .find((route) => pathname === route.href || pathname.startsWith(`${route.href}/`));

  return (
    <Menu
      className="admin-console__menu"
      mode="inline"
      theme="dark"
      items={items}
      selectedKeys={[selected?.href ?? "/admin"]}
      defaultOpenKeys={["user-management"]}
    />
  );
}

function ConsoleBrand() {
  return (
    <Link href="/admin" className="admin-console__brand" aria-label="显问 AI 平台总览">
      <span className="admin-console__brand-mark">显</span>
      <span>
        <strong>显问 AI</strong>
        <small>平台运营中心</small>
      </span>
    </Link>
  );
}

export function AdminConsoleShell({
  context,
  children,
}: {
  context: AdminContext;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const pageTitle = titleForPath(pathname);
  const identityLabel = context.commercial_identity === "SUPER_ADMIN" ? "超级管理员" : "管理员";

  const signOut = async () => {
    setLoggingOut(true);
    try {
      await logoutAdmin();
      router.replace("/admin/login");
    } finally {
      setLoggingOut(false);
    }
  };

  const sidebar = (
    <>
      <ConsoleBrand />
      <Divider className="admin-console__brand-divider" />
      <ConsoleMenu context={context} pathname={pathname} />
      <div className="admin-console__sidebar-footer">
        <span className="admin-console__status-dot" />
        平台服务运行中
      </div>
    </>
  );

  return (
    <div className="admin-console">
      <aside className="admin-console__sidebar">{sidebar}</aside>
      <Drawer
        className="admin-console__drawer"
        placement="left"
        width={264}
        open={mobileOpen}
        closable={false}
        onClose={() => setMobileOpen(false)}
      >
        {sidebar}
      </Drawer>

      <div className="admin-console__workspace">
        <header className="admin-console__header">
          <Space size="middle">
            <Button
              className="admin-console__mobile-trigger"
              type="text"
              icon={<MenuOutlined />}
              aria-label="打开后台导航"
              onClick={() => setMobileOpen(true)}
            />
            <div>
              <Typography.Text className="admin-console__breadcrumb">
                显问 AI / {pageTitle}
              </Typography.Text>
              <Typography.Title level={4}>{pageTitle}</Typography.Title>
            </div>
          </Space>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: [
                { key: "identity", label: identityLabel, disabled: true },
                { key: "logout", label: loggingOut ? "正在退出…" : "退出登录" },
              ],
              onClick: ({ key }) => {
                if (key === "logout" && !loggingOut) void signOut();
              },
            }}
          >
            <Button type="text" className="admin-console__profile">
              <Avatar size={36}>{context.nickname.slice(0, 1)}</Avatar>
              <span className="admin-console__profile-copy">
                <strong>{context.nickname}</strong>
                <small>{identityLabel}</small>
              </span>
            </Button>
          </Dropdown>
        </header>
        <main className="admin-console__content">
          {context.commercial_identity === "SUPER_ADMIN" && (
            <Tag className="admin-console__identity-tag" color="blue">
              全平台运营视图
            </Tag>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}
