"use client";

import { Alert, Space, Tag, Typography } from "antd";
import { useMemo } from "react";

import {
  parseStoredServiceArea,
  SubjectServiceAreaSelector,
  type StoredServiceArea,
} from "@/components/subject-service-area-selector";
import type { KeywordRegionSelection } from "@/lib/keywords-client";

function selectionsToStoredValue(value: readonly KeywordRegionSelection[]) {
  const nationwide = value.some((selection) => selection.level === "country");
  const stored: StoredServiceArea = {
    version: 1,
    nationwide,
    areas: nationwide
      ? []
      : value.map((selection) => ({
          code: selection.code,
          name: selection.name,
          level:
            selection.level === "country" || selection.level === "custom"
              ? "province"
              : selection.level,
          path: selection.path,
        })),
  };
  return JSON.stringify(stored);
}

export function keywordRegionSelectionsFromServiceArea(value: string): KeywordRegionSelection[] {
  const parsed = parseStoredServiceArea(value);
  if (parsed.data.nationwide) {
    return [
      {
        code: "CN",
        name: "全国",
        level: "country",
        path: [{ code: "CN", name: "全国" }],
      },
    ];
  }
  return parsed.data.areas.map((area) => ({
    code: area.code,
    name: area.name,
    level: area.level,
    path: area.path,
  }));
}

export function KeywordRegionSelector({
  mode = "custom",
  serviceRegions,
  value,
  disabled = false,
  onChange,
}: Readonly<{
  mode?: "subject" | "custom";
  serviceRegions: string;
  value: readonly KeywordRegionSelection[];
  disabled?: boolean;
  onChange: (value: KeywordRegionSelection[]) => void;
}>) {
  const subjectRegions = useMemo(
    () => keywordRegionSelectionsFromServiceArea(serviceRegions),
    [serviceRegions],
  );

  if (mode === "subject") {
    const parsed = parseStoredServiceArea(serviceRegions);
    return (
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        {subjectRegions.length ? (
          <Space wrap>
            {subjectRegions.map((selection) => (
              <Tag key={`${selection.level}-${selection.code}`} color="blue">
                {selection.path.map((item) => item.name).join(" / ")}
              </Tag>
            ))}
          </Space>
        ) : (
          <Alert type="warning" showIcon message="当前主体还没有可用的服务区域" />
        )}
        {parsed.legacyText ? (
          <Alert
            type="info"
            showIcon
            message="主体服务区域仍是旧格式"
            description="请先在主体档案中重新选择服务区域，系统才能按行政区划生成地域关键词。"
          />
        ) : null}
        <Typography.Text type="secondary">
          自动使用主体档案中的服务区域，不会修改主体资料。
        </Typography.Text>
      </Space>
    );
  }

  return (
    <SubjectServiceAreaSelector
      value={selectionsToStoredValue(value)}
      disabled={disabled}
      onChange={(next) => onChange(keywordRegionSelectionsFromServiceArea(next))}
    />
  );
}
