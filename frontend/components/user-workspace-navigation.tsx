"use client";

import { CloseOutlined, LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Drawer, Menu, Tooltip, Typography, type MenuProps } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import {
  getActiveWorkspaceNavigation,
  resolveWorkspaceNavigation,
  type ResolvedWorkspaceNavigationItem,
} from "@/components/workspace-navigation-config";
import type { WorkspaceNavigationMode } from "@/components/workspace-navigation-state";

type MenuItem = Required<MenuProps>["items"][number];

type UserWorkspaceNavigationProps = Readonly<{
  mode?: WorkspaceNavigationMode;
  drawerOpen?: boolean;
  onCollapse?: () => void;
  onExpand?: () => void;
  onDrawerOpen?: () => void;
  onDrawerClose?: () => void;
}>;

function menuItems(
  items: readonly ResolvedWorkspaceNavigationItem[],
  onNavigate?: () => void,
): MenuItem[] {
  return items.map((item) => ({
    key: item.key,
    icon: item.icon,
    disabled: item.disabled,
    label: item.href ? (
      <Link href={item.href} onClick={onNavigate}>
        {item.label}
      </Link>
    ) : (
      item.label
    ),
    children: item.children ? menuItems(item.children, onNavigate) : undefined,
  }));
}

function FullNavigationMenu({
  items,
  pathname,
  onNavigate,
}: Readonly<{
  items: readonly ResolvedWorkspaceNavigationItem[];
  pathname: string;
  onNavigate?: () => void;
}>) {
  const { selectedKey, activeGroupKey } = getActiveWorkspaceNavigation(pathname);
  const [openState, setOpenState] = useState<{ pathname: string; key: string | null }>({
    pathname,
    key: activeGroupKey,
  });
  const effectiveOpenKey = openState.pathname === pathname ? openState.key : activeGroupKey;

  return (
    <Menu
      className="geo-sidebar__menu"
      mode="inline"
      inlineIndent={18}
      items={menuItems(items, onNavigate)}
      selectedKeys={selectedKey ? [selectedKey] : []}
      openKeys={effectiveOpenKey ? [effectiveOpenKey] : []}
      onOpenChange={(keys) => {
        const next = keys.find((key) => key !== effectiveOpenKey) ?? null;
        setOpenState({ pathname, key: next });
      }}
    />
  );
}

function FullNavigationContent({
  items,
  pathname,
  currentSubjectName,
  showBrand = true,
  headerAction,
  onNavigate,
}: Readonly<{
  items: readonly ResolvedWorkspaceNavigationItem[];
  pathname: string;
  currentSubjectName: string;
  showBrand?: boolean;
  headerAction?: ReactNode;
  onNavigate?: () => void;
}>) {
  const mainItems = items.filter((item) => item.placement !== "footer");
  const footerItems = items.filter((item) => item.placement === "footer");
  const { selectedKey } = getActiveWorkspaceNavigation(pathname);

  return (
    <div className="geo-navigation-panel">
      {showBrand ? (
        <div className="geo-sidebar__brand">
          <span>
            <span className="geo-sidebar__brand-mark">显问</span>
            <Typography.Text type="secondary">GEO</Typography.Text>
          </span>
          {headerAction}
        </div>
      ) : null}

      <div className="geo-sidebar__subject">
        <Typography.Text type="secondary">主体</Typography.Text>
        <Typography.Text strong ellipsis={{ tooltip: currentSubjectName }}>
          {currentSubjectName}
        </Typography.Text>
      </div>

      <nav aria-label="GEO 工作台导航">
        <FullNavigationMenu items={mainItems} pathname={pathname} onNavigate={onNavigate} />
      </nav>

      <div className="geo-sidebar__footer">
        {footerItems.map((item) =>
          item.href ? (
            <Link
              key={item.key}
              href={item.href}
              className={[
                "geo-navigation-footer-link",
                selectedKey === item.key && "geo-navigation-footer-link--active",
              ]
                .filter(Boolean)
                .join(" ")}
              aria-label={item.label}
              aria-current={selectedKey === item.key ? "page" : undefined}
              onClick={onNavigate}
            >
              {item.icon}
              <span>{item.label}</span>
            </Link>
          ) : null,
        )}
      </div>
    </div>
  );
}

function CompactNavigation({
  items,
  pathname,
  onExpand,
}: Readonly<{
  items: readonly ResolvedWorkspaceNavigationItem[];
  pathname: string;
  onExpand: () => void;
}>) {
  const { selectedKey, activeGroupKey } = getActiveWorkspaceNavigation(pathname);
  const [flyoutState, setFlyoutState] = useState<{ pathname: string; key: string | null }>({
    pathname,
    key: null,
  });
  const [flyoutTop, setFlyoutTop] = useState(12);
  const flyoutRef = useRef<HTMLDivElement>(null);
  const flyoutTriggerRef = useRef<HTMLElement | null>(null);
  const mainItems = items.filter((item) => item.placement !== "footer");
  const footerItems = items.filter((item) => item.placement === "footer");
  const flyoutKey = flyoutState.pathname === pathname ? flyoutState.key : null;
  const flyoutItem = mainItems.find((item) => item.key === flyoutKey) ?? null;
  const closeFlyout = useCallback(() => setFlyoutState({ pathname, key: null }), [pathname]);
  const closeFlyoutAndRestoreFocus = useCallback(() => {
    flyoutTriggerRef.current?.focus();
    closeFlyout();
  }, [closeFlyout]);

  useEffect(() => {
    if (!flyoutKey) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeFlyoutAndRestoreFocus();
    };
    window.addEventListener("keydown", handleEscape);
    const timer = window.setTimeout(() => {
      flyoutRef.current?.querySelector<HTMLElement>('a:not([aria-disabled="true"])')?.focus();
    }, 0);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [closeFlyoutAndRestoreFocus, flyoutKey]);

  const openFlyout = (item: ResolvedWorkspaceNavigationItem, event: MouseEvent<HTMLElement>) => {
    if (!item.children?.length) return;
    flyoutTriggerRef.current = event.currentTarget;
    const bounds = event.currentTarget.getBoundingClientRect();
    const availableTop = Math.max(12, window.innerHeight - 430);
    setFlyoutTop(Math.min(Math.max(12, bounds.top), availableTop));
    setFlyoutState((current) => ({
      pathname,
      key: current.pathname === pathname && current.key === item.key ? null : item.key,
    }));
  };

  const railItem = (item: ResolvedWorkspaceNavigationItem) => {
    const active = selectedKey === item.key || activeGroupKey === item.key;
    const className = [
      "geo-compact-navigation__item",
      active && "geo-compact-navigation__item--active",
    ]
      .filter(Boolean)
      .join(" ");

    const control = item.children?.length ? (
      <Button
        type="text"
        className={className}
        icon={item.icon}
        aria-label={item.label}
        aria-expanded={flyoutKey === item.key}
        aria-controls={`geo-navigation-flyout-${item.key}`}
        onClick={(event) => openFlyout(item, event)}
      />
    ) : item.href ? (
      <Link
        href={item.href}
        className={className}
        aria-label={item.label}
        aria-current={active ? "page" : undefined}
        onClick={closeFlyout}
      >
        {item.icon}
      </Link>
    ) : (
      <span className={`${className} geo-compact-navigation__item--disabled`} aria-disabled="true">
        {item.icon}
      </span>
    );

    return (
      <Tooltip key={item.key} title={item.label} placement="right" mouseEnterDelay={0.35}>
        {control}
      </Tooltip>
    );
  };

  return (
    <aside className="geo-sidebar geo-sidebar--compact" aria-label="精简工作台导航">
      <div className="geo-compact-navigation__brand">
        <span className="geo-compact-navigation__brand-mark" aria-hidden="true">
          显
        </span>
        <Tooltip title="展开导航" placement="right">
          <Button
            type="text"
            icon={<RightOutlined />}
            aria-label="展开完整导航"
            onClick={onExpand}
          />
        </Tooltip>
      </div>

      <nav className="geo-compact-navigation" aria-label="GEO 工作台导航">
        {mainItems.map(railItem)}
      </nav>

      <div className="geo-compact-navigation__footer">{footerItems.map(railItem)}</div>

      {flyoutItem?.children?.length ? (
        <>
          <div
            className="geo-navigation-flyout-backdrop"
            aria-hidden="true"
            onMouseDown={closeFlyout}
          />
          <div
            ref={flyoutRef}
            id={`geo-navigation-flyout-${flyoutItem.key}`}
            className="geo-navigation-flyout"
            role="dialog"
            aria-label={`${flyoutItem.label}二级导航`}
            style={{ top: flyoutTop }}
          >
            <strong className="geo-navigation-flyout__title">{flyoutItem.label}</strong>
            <div className="geo-navigation-flyout__items">
              {flyoutItem.children.map((child) =>
                child.href && !child.disabled ? (
                  <Link
                    key={child.key}
                    href={child.href}
                    className={[
                      "geo-navigation-flyout__link",
                      selectedKey === child.key && "geo-navigation-flyout__link--active",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    aria-current={selectedKey === child.key ? "page" : undefined}
                    onClick={closeFlyout}
                  >
                    {child.label}
                  </Link>
                ) : (
                  <span
                    key={child.key}
                    className="geo-navigation-flyout__link geo-navigation-flyout__link--disabled"
                    aria-disabled="true"
                  >
                    {child.label}
                  </span>
                ),
              )}
            </div>
          </div>
        </>
      ) : null}
    </aside>
  );
}

export function UserWorkspaceNavigation({
  mode = "expanded",
  drawerOpen = false,
  onCollapse = () => undefined,
  onExpand = () => undefined,
  onDrawerOpen = () => undefined,
  onDrawerClose = () => undefined,
}: UserWorkspaceNavigationProps = {}) {
  const pathname = usePathname();
  const { active, currentSubject, user } = useSubjectWorkspace();
  const currentSubjectId = currentSubject?.id ?? null;
  const items = useMemo(() => resolveWorkspaceNavigation(currentSubjectId), [currentSubjectId]);

  if (!active || !user) return null;

  const currentSubjectName =
    currentSubject?.official_name || currentSubject?.subject_type.name || "请先绑定主体";
  const drawerMode = mode === "focus" || mode === "mobile_drawer";

  return (
    <>
      {mode === "expanded" ? (
        <aside className="geo-sidebar geo-sidebar--expanded">
          <FullNavigationContent
            items={items}
            pathname={pathname}
            currentSubjectName={currentSubjectName}
            headerAction={
              <Tooltip title="收起导航" placement="right">
                <Button
                  type="text"
                  icon={<LeftOutlined />}
                  aria-label="收起为精简导航"
                  onClick={onCollapse}
                />
              </Tooltip>
            }
          />
        </aside>
      ) : null}

      {mode === "compact" ? (
        <CompactNavigation items={items} pathname={pathname} onExpand={onExpand} />
      ) : null}

      {mode === "focus" && !drawerOpen ? (
        <Tooltip title="打开导航" placement="right">
          <Button
            className="geo-focus-edge-handle"
            type="primary"
            icon={<RightOutlined />}
            aria-label="打开专注模式导航"
            onClick={onDrawerOpen}
          />
        </Tooltip>
      ) : null}

      {drawerMode ? (
        <Drawer
          rootClassName="geo-navigation-drawer"
          placement="left"
          width={mode === "mobile_drawer" ? "min(280px, 85vw)" : 280}
          zIndex={1300}
          open={drawerOpen}
          closable={false}
          keyboard={false}
          push={false}
          title={
            <span className="geo-navigation-drawer__title">
              <strong>显问</strong>
              <span>GEO</span>
            </span>
          }
          extra={
            <Button
              type="text"
              icon={<CloseOutlined />}
              aria-label="关闭导航"
              onClick={onDrawerClose}
            />
          }
          onClose={onDrawerClose}
        >
          <FullNavigationContent
            items={items}
            pathname={pathname}
            currentSubjectName={currentSubjectName}
            showBrand={false}
            onNavigate={onDrawerClose}
          />
        </Drawer>
      ) : null}
    </>
  );
}
