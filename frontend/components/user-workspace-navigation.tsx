"use client";

import {
  ApartmentOutlined,
  AreaChartOutlined,
  BarChartOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
  ProfileOutlined,
  QuestionCircleOutlined,
  RadarChartOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Button, Divider, Menu, Typography, type MenuProps } from "antd";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";

type MenuItem = Required<MenuProps>["items"][number];

const unavailableItem = (key: string, label: string): MenuItem => ({
  key,
  label,
  disabled: true,
});

const linkedItem = (key: string, label: string, href: string): MenuItem => ({
  key,
  label: <Link href={href}>{label}</Link>,
});

function workspaceMenu(subjectId: string | null): MenuItem[] {
  const subjectHome = subjectId ? `/subjects/${subjectId}` : "/subjects";
  const keywordHome = subjectId ? `/subjects/${subjectId}/keywords` : "/subjects";
  const customKeywordHome = subjectId ? `/subjects/${subjectId}/keywords/custom` : "/subjects";
  const distillHome = subjectId ? `/subjects/${subjectId}/keywords/distill` : "/subjects";
  const assetHome = subjectId ? `/subjects/${subjectId}/keywords/assets` : "/subjects";
  const questionHome = subjectId ? `/subjects/${subjectId}/questions` : "/subjects";
  const questionManageHome = subjectId ? `/subjects/${subjectId}/questions/manage` : "/subjects";
  const articleHome = subjectId ? `/subjects/${subjectId}/articles/new` : "/subjects";
  const videoScriptHome = subjectId ? `/subjects/${subjectId}/video-scripts/new` : "/subjects";
  const videoGenerationHome = subjectId ? `/subjects/${subjectId}/videos/new` : "/subjects";
  const contentLibraryHome = subjectId ? `/subjects/${subjectId}/articles` : "/subjects";
  const imageHome = subjectId ? `/subjects/${subjectId}/images` : "/subjects";
  const imageLibraryHome = subjectId ? `/subjects/${subjectId}/image-library` : "/subjects";
  const videoLibraryHome = subjectId ? `/subjects/${subjectId}/video-library` : "/subjects";
  const customLibraryHome = subjectId ? `/subjects/${subjectId}/custom-library` : "/subjects";
  const publicationCheckHome = subjectId
    ? `/subjects/${subjectId}/publication-checks`
    : "/subjects";

  return [
    {
      key: "overview",
      icon: <AreaChartOutlined />,
      label: <Link href="/workspace">GEO 总览</Link>,
    },
    {
      key: "subject",
      icon: <ProfileOutlined />,
      label: "主体档案",
      children: [
        linkedItem("subject-edit", "编辑主体", subjectHome),
        linkedItem("subject-manage", "主体管理", "/subjects"),
      ],
    },
    {
      key: "keywords",
      icon: <TagsOutlined />,
      label: "关键词中心",
      children: [
        linkedItem("keywords-smart", "智能关键词", keywordHome),
        linkedItem("keywords-custom", "自定义关键词", customKeywordHome),
        linkedItem("keywords-distill", "关键词蒸馏", distillHome),
        linkedItem("keywords-assets", "关键词资产", assetHome),
      ],
    },
    {
      key: "questions",
      icon: <QuestionCircleOutlined />,
      label: "问题库",
      children: [
        linkedItem("questions-generate", "问题生成", questionHome),
        linkedItem("questions-manage", "问题管理", questionManageHome),
      ],
    },
    {
      key: "detections",
      icon: <RadarChartOutlined />,
      label: "检测中心",
      children: [
        linkedItem("detections-subject", "主体检测", "/geo/detections"),
        linkedItem("detections-website", "官网检测", "/geo/website-audits"),
        linkedItem("detections-publication", "发布检测", publicationCheckHome),
      ],
    },
    {
      key: "insights",
      icon: <BarChartOutlined />,
      label: "GEO 洞察",
      children: [
        linkedItem("insights-reports", "检测报告", "/geo/reports"),
        linkedItem("insights-history", "历史报告对比", "/geo/reports/history"),
      ],
    },
    {
      key: "data-center",
      icon: <DatabaseOutlined />,
      label: "数据中心",
      children: [
        linkedItem("data-exposure", "曝光指数", "/geo/exposure"),
        linkedItem("data-competitors", "竞品对比", "/geo/data-center/competitors"),
        linkedItem("data-source", "信源指数", "/geo/data-center/source-index"),
        linkedItem("data-negative", "负面信息指数", "/geo/data-center/negative-index"),
      ],
    },
    {
      key: "knowledge-graph",
      icon: <ApartmentOutlined />,
      label: "知识图谱建设",
      children: [
        linkedItem("knowledge-subject", "主体实体建设", "/geo/knowledge-graph/subjects"),
        linkedItem("knowledge-map", "地图实体建设", "/geo/knowledge-graph/maps"),
        linkedItem("knowledge-website", "官网实体建设", "/geo/knowledge-graph/websites"),
        linkedItem("knowledge-media", "媒体信号建设", "/geo/knowledge-graph/media-signals"),
      ],
    },
    {
      key: "optimization",
      icon: <FundProjectionScreenOutlined />,
      label: "优化中心",
      children: [
        linkedItem("optimization-strategy", "优化方案", "/geo/strategy"),
        unavailableItem("optimization-execution", "执行计划"),
        linkedItem("optimization-articles", "文章生成", articleHome),
        linkedItem("optimization-images", "图片生成", imageHome),
        linkedItem("optimization-video", "视频脚本生成", videoScriptHome),
        linkedItem("optimization-video-generation", "视频生成", videoGenerationHome),
      ],
    },
    {
      key: "content",
      icon: <FileTextOutlined />,
      label: "内容资产中心",
      children: [
        linkedItem("content-library", "内容库", contentLibraryHome),
        linkedItem("content-image-library", "图片库", imageLibraryHome),
        linkedItem("content-video-library", "视频库", videoLibraryHome),
        linkedItem("content-custom-library", "自定义库", customLibraryHome),
      ],
    },
  ];
}

function selectedMenuKey(pathname: string) {
  if (pathname === "/workspace") return "overview";
  if (pathname === "/subjects") return "subject-manage";
  if (/^\/subjects\/[^/]+$/.test(pathname)) return "subject-edit";
  if (pathname.includes("/keywords/distill")) return "keywords-distill";
  if (pathname.includes("/keywords/assets")) return "keywords-assets";
  if (pathname.includes("/keywords/custom")) return "keywords-custom";
  if (pathname.includes("/keywords")) return "keywords-smart";
  if (pathname.includes("/questions/manage")) return "questions-manage";
  if (pathname.includes("/questions")) return "questions-generate";
  if (pathname.startsWith("/geo/website-audits")) return "detections-website";
  if (pathname.startsWith("/geo/detections")) return "detections-subject";
  if (pathname.includes("/publication-checks")) return "detections-publication";
  if (/^\/geo\/reports\/[^/]+\/strategy(?:\/|$)/.test(pathname)) {
    return "optimization-strategy";
  }
  if (/^\/geo\/reports\/history(?:\/|$)/.test(pathname)) return "insights-history";
  if (/^\/geo\/exposure(?:\/|$)/.test(pathname)) return "data-exposure";
  if (/^\/geo\/data-center\/competitors(?:\/|$)/.test(pathname)) {
    return "data-competitors";
  }
  if (/^\/geo\/data-center\/source-index(?:\/|$)/.test(pathname)) return "data-source";
  if (/^\/geo\/data-center\/negative-index(?:\/|$)/.test(pathname)) {
    return "data-negative";
  }
  if (pathname.startsWith("/geo/reports")) return "insights-reports";
  if (pathname.startsWith("/geo/knowledge-graph/media-signals")) return "knowledge-media";
  if (pathname.startsWith("/geo/knowledge-graph/websites")) return "knowledge-website";
  if (pathname.startsWith("/geo/knowledge-graph/subjects")) return "knowledge-subject";
  if (pathname.startsWith("/geo/knowledge-graph/maps")) return "knowledge-map";
  if (pathname.startsWith("/geo/strategy") || pathname.includes("/strategy")) {
    return "optimization-strategy";
  }
  if (pathname.includes("/image-library")) return "content-image-library";
  if (pathname.includes("/video-library")) return "content-video-library";
  if (pathname.includes("/custom-library")) return "content-custom-library";
  if (/^\/subjects\/[^/]+\/articles\/?$/.test(pathname)) return "content-library";
  if (pathname.includes("/images")) return "optimization-images";
  if (pathname.includes("/video-scripts")) return "optimization-video";
  if (/^\/subjects\/[^/]+\/videos(?:\/|$)/.test(pathname)) {
    return "optimization-video-generation";
  }
  if (pathname.includes("/articles")) return "optimization-articles";
  return "";
}

const menuGroupByChild: Readonly<Record<string, string>> = {
  "subject-edit": "subject",
  "subject-manage": "subject",
  "keywords-smart": "keywords",
  "keywords-custom": "keywords",
  "keywords-distill": "keywords",
  "keywords-assets": "keywords",
  "questions-generate": "questions",
  "questions-manage": "questions",
  "detections-subject": "detections",
  "detections-website": "detections",
  "detections-publication": "detections",
  "insights-reports": "insights",
  "insights-history": "insights",
  "data-exposure": "data-center",
  "data-competitors": "data-center",
  "data-source": "data-center",
  "data-negative": "data-center",
  "knowledge-subject": "knowledge-graph",
  "knowledge-map": "knowledge-graph",
  "knowledge-website": "knowledge-graph",
  "knowledge-media": "knowledge-graph",
  "optimization-strategy": "optimization",
  "optimization-execution": "optimization",
  "optimization-articles": "optimization",
  "optimization-images": "optimization",
  "optimization-video": "optimization",
  "optimization-video-generation": "optimization",
  "content-library": "content",
  "content-image-library": "content",
  "content-video-library": "content",
  "content-custom-library": "content",
};

export function UserWorkspaceNavigation() {
  const pathname = usePathname();
  const { active, currentSubject, user } = useSubjectWorkspace();
  const selectedKey = selectedMenuKey(pathname);
  const activeGroup = menuGroupByChild[selectedKey] ?? null;
  const [openState, setOpenState] = useState<{
    pathname: string;
    key: string | null;
  }>({ pathname, key: activeGroup });
  if (!active || !user) return null;
  const currentSubjectId = currentSubject?.id ?? null;
  const currentSubjectName =
    currentSubject?.official_name || currentSubject?.subject_type.name || "尚未选择主体";
  const effectiveOpenKey = openState.pathname === pathname ? openState.key : activeGroup;

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
        <Menu
          className="geo-sidebar__menu"
          mode="inline"
          inlineIndent={18}
          items={workspaceMenu(currentSubjectId)}
          selectedKeys={selectedKey ? [selectedKey] : []}
          openKeys={effectiveOpenKey ? [effectiveOpenKey] : []}
          onOpenChange={(keys) => {
            const next = keys.find((key) => key !== effectiveOpenKey) ?? null;
            setOpenState({ pathname, key: next });
          }}
        />
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
