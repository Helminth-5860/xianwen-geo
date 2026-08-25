"use client";

import { Alert, Button, Cascader, Checkbox, Empty, Select, Space, Tag, Typography } from "antd";
import { useMemo, useRef, useState } from "react";

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

type StoredAreaNode = Readonly<{ code: string; name: string }>;

type StreetOption = Readonly<{ value: string; label: string }>;

type StoredServiceArea = Readonly<{
  version: 1;
  nationwide: boolean;
  areas: ReadonlyArray<{
    code: string;
    name: string;
    level: "province" | "city" | "district" | "street";
    path: readonly StoredAreaNode[];
  }>;
}>;

const DIRECT_MUNICIPALITY_CODES = new Set(["110000", "120000", "310000", "500000"]);
const NON_MAINLAND_CODES = new Set(["710000", "810000", "820000"]);

function toOption(node: DivisionNode): DivisionOption {
  return {
    value: node.code,
    label: node.name,
    children: node.children?.map(toOption),
  };
}

const emptyArea: StoredServiceArea = { version: 1, nationwide: false, areas: [] };

function parseStoredValue(value: unknown): { data: StoredServiceArea; legacyText: string } {
  if (typeof value !== "string" || !value.trim()) return { data: emptyArea, legacyText: "" };
  if (["全国", "全国范围", "全国服务"].includes(value.trim())) {
    return { data: { version: 1, nationwide: true, areas: [] }, legacyText: "" };
  }
  try {
    const parsed = JSON.parse(value) as Partial<StoredServiceArea>;
    if (
      parsed.version === 1 &&
      typeof parsed.nationwide === "boolean" &&
      Array.isArray(parsed.areas)
    ) {
      return {
        data: {
          version: 1,
          nationwide: parsed.nationwide,
          areas: parsed.areas.filter(
            (area) =>
              area &&
              typeof area.code === "string" &&
              typeof area.name === "string" &&
              Array.isArray(area.path),
          ) as StoredServiceArea["areas"],
        },
        legacyText: "",
      };
    }
  } catch {
    // Legacy free text remains untouched until the user makes an explicit selection.
  }
  return { data: emptyArea, legacyText: value };
}

function serialize(value: StoredServiceArea) {
  return JSON.stringify(value);
}

function resolvePath(
  mainlandOptions: DivisionOption[],
  codes: readonly string[],
): StoredAreaNode[] {
  const path: StoredAreaNode[] = [];
  let options: DivisionOption[] | undefined = mainlandOptions;
  for (const code of codes) {
    const current: DivisionOption | undefined = options?.find((option) => option.value === code);
    if (!current) return [];
    path.push({ code: current.value, name: current.label });
    options = current.children;
  }
  return path;
}

function areaLevel(path: readonly StoredAreaNode[], hasStreet: boolean) {
  if (hasStreet) return "street" as const;
  if (path.length <= 1) return "province" as const;
  if (path.length >= 3 || DIRECT_MUNICIPALITY_CODES.has(path[0]?.code ?? "")) {
    return "district" as const;
  }
  return "city" as const;
}

export function isDistrictSelection(path: readonly string[]) {
  return path.length >= 3 || (path.length >= 2 && DIRECT_MUNICIPALITY_CODES.has(path[0] ?? ""));
}

const streetCache = new Map<string, StreetOption[]>();

export function SubjectServiceAreaSelector({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const parsed = useMemo(() => parseStoredValue(value), [value]);
  const [selectedPath, setSelectedPath] = useState<string[]>([]);
  const [selectedStreet, setSelectedStreet] = useState<string>();
  const [streetOptions, setStreetOptions] = useState<StreetOption[]>([]);
  const [validationMessage, setValidationMessage] = useState("");
  const [mainlandOptions, setMainlandOptions] = useState<DivisionOption[]>([]);
  const [loadingOptions, setLoadingOptions] = useState(false);
  const [loadingStreets, setLoadingStreets] = useState(false);
  const streetRequestId = useRef(0);

  const update = (next: StoredServiceArea) => {
    setValidationMessage("");
    onChange(serialize(next));
  };

  const loadDivisionOptions = async () => {
    if (mainlandOptions.length || loadingOptions) return;
    setLoadingOptions(true);
    try {
      const divisionModule = await import("@province-city-china/level");
      setMainlandOptions(
        (divisionModule.default as readonly DivisionNode[])
          .filter((node) => !NON_MAINLAND_CODES.has(node.code))
          .map(toOption),
      );
    } catch {
      setValidationMessage("行政区划数据暂时无法加载，请稍后重试");
    } finally {
      setLoadingOptions(false);
    }
  };

  const loadStreetOptions = async (path: readonly string[]) => {
    const requestId = ++streetRequestId.current;
    const districtCode = path[path.length - 1];
    if (!isDistrictSelection(path) || !districtCode) {
      setStreetOptions([]);
      setLoadingStreets(false);
      return;
    }
    const cached = streetCache.get(districtCode);
    if (cached) {
      setStreetOptions(cached);
      setLoadingStreets(false);
      return;
    }
    setLoadingStreets(true);
    try {
      const response = await fetch(`/region-data/towns/${encodeURIComponent(districtCode)}`, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Town data request failed");
      const payload = (await response.json()) as { towns?: unknown };
      const options = Array.isArray(payload.towns)
        ? payload.towns.filter(
            (item): item is StreetOption =>
              typeof item === "object" &&
              item !== null &&
              typeof (item as StreetOption).value === "string" &&
              typeof (item as StreetOption).label === "string",
          )
        : [];
      streetCache.set(districtCode, options);
      if (streetRequestId.current === requestId) setStreetOptions(options);
    } catch {
      if (streetRequestId.current === requestId) {
        setStreetOptions([]);
        setValidationMessage("乡镇街道数据暂时无法加载，可先保存到区县后稍后补充");
      }
    } finally {
      if (streetRequestId.current === requestId) setLoadingStreets(false);
    }
  };

  const addArea = () => {
    const path = resolvePath(mainlandOptions, selectedPath);
    if (!path.length) {
      setValidationMessage("请先选择省、市或区县");
      return;
    }
    const streetOption = streetOptions.find((option) => option.value === selectedStreet);
    const street = streetOption
      ? { code: streetOption.value, name: streetOption.label }
      : undefined;
    const fullPath = street ? [...path, street] : path;
    const leaf = fullPath[fullPath.length - 1];
    if (!leaf) return;
    const candidate = {
      code: leaf.code,
      name: leaf.name,
      level: areaLevel(path, Boolean(street)),
      path: fullPath,
    };
    const exists = parsed.data.areas.some(
      (area) =>
        area.code === candidate.code &&
        area.path.map((item) => item.code).join("/") ===
          fullPath.map((item) => item.code).join("/"),
    );
    if (!exists) {
      update({ version: 1, nationwide: false, areas: [...parsed.data.areas, candidate] });
    }
    setSelectedPath([]);
    setSelectedStreet(undefined);
    setStreetOptions([]);
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
            areas: event.target.checked ? [] : parsed.data.areas,
          })
        }
      >
        支持全国
      </Checkbox>
      {!parsed.data.nationwide && (
        <>
          <Cascader
            aria-label="省市区县"
            value={selectedPath}
            disabled={disabled}
            changeOnSelect
            showSearch
            options={mainlandOptions}
            placeholder={loadingOptions ? "正在加载行政区划…" : "选择省 / 市 / 区县"}
            style={{ width: "100%" }}
            onChange={(next) => {
              const path = next.map(String);
              setSelectedPath(path);
              setSelectedStreet(undefined);
              setValidationMessage("");
              void loadStreetOptions(path);
            }}
            onOpenChange={(open) => {
              if (open) void loadDivisionOptions();
            }}
          />
          <div className="subject-area-street-grid">
            <Select
              aria-label="乡镇或街道"
              value={selectedStreet}
              disabled={disabled || !isDistrictSelection(selectedPath)}
              loading={loadingStreets}
              allowClear
              showSearch
              optionFilterProp="label"
              options={streetOptions}
              placeholder={
                !isDistrictSelection(selectedPath)
                  ? "请先选择到区县"
                  : loadingStreets
                    ? "正在加载乡镇街道…"
                    : "选择乡镇 / 街道（选填）"
              }
              onChange={setSelectedStreet}
            />
            <Button disabled={disabled} onClick={addArea}>
              添加服务区域
            </Button>
          </div>
        </>
      )}
      {validationMessage && <Alert type="warning" showIcon message={validationMessage} />}
      {parsed.legacyText && (
        <Alert
          type="info"
          showIcon
          message="已保留原服务地区"
          description={`${parsed.legacyText}。重新选择后将升级为行政区划代码和名称。`}
        />
      )}
      {!parsed.data.nationwide && parsed.data.areas.length === 0 && !parsed.legacyText ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未添加服务区域" />
      ) : (
        <Space wrap>
          {parsed.data.areas.map((area) => (
            <Tag
              key={`${area.path.map((item) => item.code).join("-")}-${area.level}`}
              closable={!disabled}
              onClose={() =>
                update({
                  version: 1,
                  nationwide: false,
                  areas: parsed.data.areas.filter((item) => item !== area),
                })
              }
            >
              {area.path.map((item) => item.name).join(" / ")}
            </Tag>
          ))}
        </Space>
      )}
      <Typography.Text type="secondary">
        支持多选；可选择到省、市、区县或乡镇街道，系统同时保存行政区划代码与名称。门牌号请在上方经营地址中填写。
      </Typography.Text>
    </Space>
  );
}
