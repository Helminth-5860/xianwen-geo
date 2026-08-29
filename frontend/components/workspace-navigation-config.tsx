import {
  ApartmentOutlined,
  AreaChartOutlined,
  BarChartOutlined,
  CreditCardOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
  ProfileOutlined,
  QuestionCircleOutlined,
  RadarChartOutlined,
  ShopOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import type { ReactNode } from "react";

export type WorkspaceNavigationPlacement = "main" | "footer";

export type WorkspaceNavigationItem = Readonly<{
  key: string;
  label: string;
  icon?: ReactNode;
  href?: string | ((subjectId: string | null) => string);
  disabled?: boolean;
  placement?: WorkspaceNavigationPlacement;
  activePriority?: number;
  isActive?: (pathname: string) => boolean;
  children?: readonly WorkspaceNavigationItem[];
}>;

const subjectRoute =
  (suffix = "") =>
  (subjectId: string | null) =>
    subjectId ? `/subjects/${subjectId}${suffix}` : "/subjects";

const pathStartsWith = (prefix: string) => (pathname: string) =>
  pathname === prefix || pathname.startsWith(`${prefix}/`);

export const navigationConfig: readonly WorkspaceNavigationItem[] = [
  {
    key: "overview",
    label: "GEO 总览",
    icon: <AreaChartOutlined />,
    href: "/workspace",
    isActive: (pathname) => pathname === "/workspace",
  },
  {
    key: "subject",
    label: "主体档案",
    icon: <ProfileOutlined />,
    children: [
      {
        key: "subject-edit",
        label: "编辑主体",
        href: subjectRoute(),
        isActive: (pathname) => /^\/subjects\/[^/]+$/.test(pathname),
      },
      {
        key: "subject-competitors",
        label: "竞品管理",
        href: subjectRoute("/competitors"),
        isActive: (pathname) => /^\/subjects\/[^/]+\/competitors(?:\/|$)/.test(pathname),
      },
      {
        key: "subject-manage",
        label: "主体管理",
        href: "/subjects",
        isActive: (pathname) => pathname === "/subjects",
      },
    ],
  },
  {
    key: "keywords",
    label: "关键词中心",
    icon: <TagsOutlined />,
    children: [
      {
        key: "keywords-smart",
        label: "智能关键词",
        href: subjectRoute("/keywords"),
        isActive: (pathname) => /^\/subjects\/[^/]+\/keywords\/?$/.test(pathname),
      },
      {
        key: "keywords-custom",
        label: "自定义关键词",
        href: subjectRoute("/keywords/custom"),
        isActive: (pathname) => pathname.includes("/keywords/custom"),
      },
      {
        key: "keywords-distill",
        label: "关键词蒸馏",
        href: subjectRoute("/keywords/distill"),
        isActive: (pathname) => pathname.includes("/keywords/distill"),
      },
      {
        key: "keywords-assets",
        label: "关键词资产",
        href: subjectRoute("/keywords/assets"),
        isActive: (pathname) => pathname.includes("/keywords/assets"),
      },
    ],
  },
  {
    key: "questions",
    label: "问题库",
    icon: <QuestionCircleOutlined />,
    children: [
      {
        key: "questions-generate",
        label: "问题生成",
        href: subjectRoute("/questions"),
        isActive: (pathname) => /^\/subjects\/[^/]+\/questions\/?$/.test(pathname),
      },
      {
        key: "questions-manage",
        label: "问题管理",
        href: subjectRoute("/questions/manage"),
        isActive: (pathname) => pathname.includes("/questions/manage"),
      },
    ],
  },
  {
    key: "detections",
    label: "检测中心",
    icon: <RadarChartOutlined />,
    children: [
      {
        key: "detections-subject",
        label: "主体检测",
        href: "/geo/detections",
        isActive: pathStartsWith("/geo/detections"),
      },
      {
        key: "detections-website",
        label: "官网检测",
        href: "/geo/website-audits",
        isActive: pathStartsWith("/geo/website-audits"),
      },
      {
        key: "detections-publication",
        label: "发布检测",
        href: subjectRoute("/publication-checks"),
        isActive: (pathname) => pathname.includes("/publication-checks"),
      },
    ],
  },
  {
    key: "insights",
    label: "GEO 洞察",
    icon: <BarChartOutlined />,
    children: [
      {
        key: "insights-reports",
        label: "检测报告",
        href: "/geo/reports",
        activePriority: 10,
        isActive: pathStartsWith("/geo/reports"),
      },
      {
        key: "insights-history",
        label: "历史报告对比",
        href: "/geo/reports/history",
        activePriority: 80,
        isActive: pathStartsWith("/geo/reports/history"),
      },
    ],
  },
  {
    key: "data-center",
    label: "数据中心",
    icon: <DatabaseOutlined />,
    children: [
      {
        key: "data-exposure",
        label: "曝光指数",
        href: "/geo/exposure",
        isActive: pathStartsWith("/geo/exposure"),
      },
      {
        key: "data-competitors",
        label: "竞品对比",
        href: "/geo/data-center/competitors",
        isActive: pathStartsWith("/geo/data-center/competitors"),
      },
      {
        key: "data-source",
        label: "信源指数",
        href: "/geo/data-center/source-index",
        isActive: pathStartsWith("/geo/data-center/source-index"),
      },
      {
        key: "data-negative",
        label: "负面信息指数",
        href: "/geo/data-center/negative-index",
        isActive: pathStartsWith("/geo/data-center/negative-index"),
      },
    ],
  },
  {
    key: "knowledge-graph",
    label: "知识图谱建设",
    icon: <ApartmentOutlined />,
    children: [
      {
        key: "knowledge-subject",
        label: "主体实体建设",
        href: "/geo/knowledge-graph/subjects",
        isActive: pathStartsWith("/geo/knowledge-graph/subjects"),
      },
      {
        key: "knowledge-map",
        label: "地图实体建设",
        href: "/geo/knowledge-graph/maps",
        isActive: pathStartsWith("/geo/knowledge-graph/maps"),
      },
      {
        key: "knowledge-website",
        label: "官网实体建设",
        href: "/geo/knowledge-graph/websites",
        isActive: pathStartsWith("/geo/knowledge-graph/websites"),
      },
      {
        key: "knowledge-media",
        label: "媒体信号建设",
        href: "/geo/knowledge-graph/media-signals",
        isActive: pathStartsWith("/geo/knowledge-graph/media-signals"),
      },
    ],
  },
  {
    key: "optimization",
    label: "优化中心",
    icon: <FundProjectionScreenOutlined />,
    children: [
      {
        key: "optimization-strategy",
        label: "优化方案",
        href: "/geo/strategy",
        activePriority: 100,
        isActive: (pathname) =>
          pathStartsWith("/geo/strategy")(pathname) ||
          /^\/geo\/reports\/[^/]+\/strategy(?:\/|$)/.test(pathname) ||
          pathname.includes("/strategy"),
      },
      {
        key: "optimization-execution",
        label: "执行计划",
        href: "/geo/execution",
        isActive: pathStartsWith("/geo/execution"),
      },
      {
        key: "optimization-paid-media",
        label: "付费媒体",
        icon: <ShopOutlined />,
        href: subjectRoute("/paid-media"),
        isActive: (pathname) => pathname.includes("/paid-media"),
      },
      {
        key: "optimization-auto-publishing",
        label: "自动发文",
        href: "/geo/optimization/auto-publishing",
        isActive: pathStartsWith("/geo/optimization/auto-publishing"),
      },
      {
        key: "optimization-articles",
        label: "文章生成",
        href: subjectRoute("/articles/new"),
        isActive: (pathname) => pathname.includes("/articles/new"),
      },
      {
        key: "optimization-images",
        label: "图片生成",
        href: subjectRoute("/images"),
        isActive: (pathname) => /^\/subjects\/[^/]+\/images(?:\/|$)/.test(pathname),
      },
      {
        key: "optimization-video",
        label: "视频脚本生成",
        href: subjectRoute("/video-scripts/new"),
        isActive: (pathname) => pathname.includes("/video-scripts"),
      },
      {
        key: "optimization-video-generation",
        label: "视频生成",
        href: subjectRoute("/videos/new"),
        isActive: (pathname) => /^\/subjects\/[^/]+\/videos(?:\/|$)/.test(pathname),
      },
    ],
  },
  {
    key: "content",
    label: "内容资产中心",
    icon: <FileTextOutlined />,
    children: [
      {
        key: "content-library",
        label: "内容库",
        href: subjectRoute("/articles"),
        activePriority: 50,
        isActive: (pathname) => /^\/subjects\/[^/]+\/articles\/?$/.test(pathname),
      },
      {
        key: "content-image-library",
        label: "图片库",
        href: subjectRoute("/image-library"),
        activePriority: 50,
        isActive: (pathname) => pathname.includes("/image-library"),
      },
      {
        key: "content-video-library",
        label: "视频库",
        href: subjectRoute("/video-library"),
        activePriority: 50,
        isActive: (pathname) => pathname.includes("/video-library"),
      },
      {
        key: "content-custom-library",
        label: "自定义库",
        href: subjectRoute("/custom-library"),
        activePriority: 50,
        isActive: (pathname) => pathname.includes("/custom-library"),
      },
    ],
  },
  {
    key: "subscription",
    label: "套餐与额度",
    icon: <CreditCardOutlined />,
    href: "/subscription",
    placement: "footer",
    isActive: pathStartsWith("/subscription"),
  },
] as const;

export type ResolvedWorkspaceNavigationItem = Omit<WorkspaceNavigationItem, "href" | "children"> &
  Readonly<{
    href?: string;
    children?: readonly ResolvedWorkspaceNavigationItem[];
  }>;

export function resolveWorkspaceNavigation(subjectId: string | null) {
  const resolveItem = (item: WorkspaceNavigationItem): ResolvedWorkspaceNavigationItem => ({
    ...item,
    href: typeof item.href === "function" ? item.href(subjectId) : item.href,
    children: item.children?.map(resolveItem),
  });
  return navigationConfig.map(resolveItem);
}

export function getActiveWorkspaceNavigation(pathname: string) {
  const matches: Array<{
    item: WorkspaceNavigationItem;
    parentKey: string | null;
    order: number;
  }> = [];
  let order = 0;

  for (const item of navigationConfig) {
    if (item.isActive?.(pathname)) matches.push({ item, parentKey: null, order });
    order += 1;
    for (const child of item.children ?? []) {
      if (child.isActive?.(pathname)) {
        matches.push({ item: child, parentKey: item.key, order });
      }
      order += 1;
    }
  }

  const bestMatch = matches.sort(
    (left, right) =>
      (right.item.activePriority ?? 0) - (left.item.activePriority ?? 0) ||
      right.order - left.order,
  )[0];

  return {
    selectedKey: bestMatch?.item.key ?? "",
    activeGroupKey: bestMatch?.parentKey ?? null,
  } as const;
}
