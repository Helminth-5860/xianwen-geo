"use client";

import { Alert, Button, Cascader, Checkbox, Empty, Space, Tag, Typography } from "antd";
import { useMemo, useState } from "react";

import {
  parseStoredServiceArea,
  type StoredAreaNode,
  type StoredServiceArea,
} from "@/components/subject-service-area-selector";

type DivisionNode = Readonly<{
  code: string;
  name: string;
  children?: readonly DivisionNode[];
}>;

type DivisionOption = {
  value: string;
  label: string;
  children?: DivisionOption[];
};

const DIRECT_MUNICIPALITY_CODES = new Set(["110000", "120000", "310000", "500000"]);
const NON_MAINLAND_CODES = new Set(["710000", "810000", "820000"]);

function toCoverageOption(node: DivisionNode): DivisionOption {
  return {
    value: node.code,
    label: node.name,
    children: DIRECT_MUNICIPALITY_CODES.has(node.code)
      ? undefined
      : node.children?.map((child) => ({ value: child.code, label: child.name })),
  };
}

function normalizedAreas(areas: StoredServiceArea["areas"]): StoredServiceArea["areas"] {
  const normalized = areas.map((area) => {
    const first = area.path[0];
    if (!first) return null;
    const directMunicipality = DIRECT_MUNICIPALITY_CODES.has(first.code);
    const path = directMunicipality ? [first] : area.path.slice(0, Math.min(2, area.path.length));
    const leaf = path[path.length - 1];
    if (!leaf) return null;
    return {
      code: leaf.code,
      name: leaf.name,
      level: directMunicipality || path.length === 2 ? ("city" as const) : ("province" as const),
      path,
    };
  });
  const unique = new Map<string, NonNullable<(typeof normalized)[number]>>();
  for (const area of normalized) {
    if (area) unique.set(`${area.level}:${area.code}`, area);
  }
  return [...unique.values()];
}

export function normalizeBusinessCoverage(value: unknown) {
  const parsed = parseStoredServiceArea(value);
  if (parsed.legacyText) return parsed.legacyText;
  return JSON.stringify({
    version: 1,
    nationwide: parsed.data.nationwide,
    areas: parsed.data.nationwide ? [] : normalizedAreas(parsed.data.areas),
  } satisfies StoredServiceArea);
}

export function businessCoverageIsComplete(value: unknown) {
  const parsed = parseStoredServiceArea(normalizeBusinessCoverage(value));
  return Boolean(
    !parsed.legacyText && (parsed.data.nationwide || normalizedAreas(parsed.data.areas).length),
  );
}

function resolvePath(options: DivisionOption[], codes: readonly string[]): StoredAreaNode[] {
  const path: StoredAreaNode[] = [];
  let level: DivisionOption[] | undefined = options;
  for (const code of codes) {
    const current: DivisionOption | undefined = level?.find((option) => option.value === code);
    if (!current) return [];
    path.push({ code: current.value, name: current.label });
    level = current.children;
  }
  return path;
}

export function SubjectBusinessCoverageSelector({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const parsed = useMemo(() => parseStoredServiceArea(value), [value]);
  const areas = useMemo(() => normalizedAreas(parsed.data.areas), [parsed.data.areas]);
  const [selectedPath, setSelectedPath] = useState<string[]>([]);
  const [options, setOptions] = useState<DivisionOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const update = (next: StoredServiceArea) => {
    setMessage("");
    onChange(JSON.stringify(next));
  };

  const loadOptions = async () => {
    if (options.length || loading) return;
    setLoading(true);
    try {
      const divisionModule = await import("@province-city-china/level");
      setOptions(
        (divisionModule.default as readonly DivisionNode[])
          .filter((node) => !NON_MAINLAND_CODES.has(node.code))
          .map(toCoverageOption),
      );
    } catch {
      setMessage("行政区划暂时无法加载，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  const addArea = () => {
    const path = resolvePath(options, selectedPath);
    if (!path.length) {
      setMessage("请先选择省或市");
      return;
    }
    const leaf = path[path.length - 1];
    const directMunicipality = DIRECT_MUNICIPALITY_CODES.has(path[0]?.code ?? "");
    const candidate = {
      code: leaf.code,
      name: leaf.name,
      level: directMunicipality || path.length === 2 ? ("city" as const) : ("province" as const),
      path,
    };
    const nextAreas = areas.some(
      (area) => area.code === candidate.code && area.level === candidate.level,
    )
      ? areas
      : [...areas, candidate];
    update({ version: 1, nationwide: false, areas: nextAreas });
    setSelectedPath([]);
  };

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Checkbox
        checked={parsed.data.nationwide}
        disabled={disabled}
        onChange={(event) =>
          update({
            version: 1,
            nationwide: event.target.checked,
            areas: event.target.checked ? [] : areas,
          })
        }
      >
        业务覆盖全国
      </Checkbox>
      {!parsed.data.nationwide && (
        <div className="subject-area-street-grid">
          <Cascader
            aria-label="业务覆盖省市"
            value={selectedPath}
            disabled={disabled}
            changeOnSelect
            showSearch
            options={options}
            placeholder={loading ? "正在加载行政区划…" : "选择省或市"}
            style={{ width: "100%" }}
            onChange={(next) => {
              setSelectedPath(next.map(String));
              setMessage("");
            }}
            onOpenChange={(open) => {
              if (open) void loadOptions();
            }}
          />
          <Button disabled={disabled} onClick={addArea}>
            添加覆盖区域
          </Button>
        </div>
      )}
      {message && <Alert type="warning" showIcon message={message} />}
      {parsed.legacyText && (
        <Alert
          type="info"
          showIcon
          message="原业务覆盖区域已保留"
          description="请重新选择全国、省或市后保存。"
        />
      )}
      {!parsed.data.nationwide && !areas.length && !parsed.legacyText ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未添加业务覆盖区域" />
      ) : (
        <Space wrap>
          {areas.map((area) => (
            <Tag
              key={`${area.level}:${area.code}`}
              closable={!disabled}
              onClose={() =>
                update({
                  version: 1,
                  nationwide: false,
                  areas: areas.filter((item) => item !== area),
                })
              }
            >
              {area.path.map((node) => node.name).join(" / ")}
            </Tag>
          ))}
        </Space>
      )}
      <Typography.Text type="secondary">
        表示产品或服务实际覆盖范围，可选择全国、一个或多个省市，与主体地址互不影响。
      </Typography.Text>
    </Space>
  );
}
