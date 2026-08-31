"use client";

import { Alert, Cascader, Input, Space, Typography } from "antd";
import { useMemo, useState } from "react";

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

type AddressNode = Readonly<{ code: string; name: string }>;

export type StoredBusinessAddress = Readonly<{
  version: 1;
  path: readonly AddressNode[];
  detail: string;
}>;

const DIRECT_MUNICIPALITY_CODES = new Set(["110000", "120000", "310000", "500000"]);
const NON_MAINLAND_CODES = new Set(["710000", "810000", "820000"]);
const emptyAddress: StoredBusinessAddress = { version: 1, path: [], detail: "" };

function toOption(node: DivisionNode): DivisionOption {
  return {
    value: node.code,
    label: node.name,
    children: node.children?.map(toOption),
  };
}

export function parseStoredBusinessAddress(value: unknown): {
  data: StoredBusinessAddress;
  legacyText: string;
} {
  if (typeof value !== "string" || !value.trim()) {
    return { data: emptyAddress, legacyText: "" };
  }
  try {
    const parsed = JSON.parse(value) as Partial<StoredBusinessAddress>;
    if (parsed.version === 1 && Array.isArray(parsed.path) && typeof parsed.detail === "string") {
      const path = parsed.path.filter((node): node is AddressNode =>
        Boolean(
          node &&
          typeof node.code === "string" &&
          node.code &&
          typeof node.name === "string" &&
          node.name,
        ),
      );
      return { data: { version: 1, path, detail: parsed.detail }, legacyText: "" };
    }
  } catch {
    // Existing free-text addresses stay visible until the user confirms a division.
  }
  return { data: emptyAddress, legacyText: value.trim() };
}

export function businessAddressIsComplete(value: unknown) {
  const parsed = parseStoredBusinessAddress(value);
  if (parsed.legacyText || !parsed.data.detail.trim() || !parsed.data.path.length) return false;
  const minimumDepth = DIRECT_MUNICIPALITY_CODES.has(parsed.data.path[0]?.code ?? "") ? 1 : 2;
  return parsed.data.path.length >= minimumDepth && parsed.data.path.length <= 3;
}

function serializeAddress(value: StoredBusinessAddress) {
  return JSON.stringify(value);
}

export function SubjectBusinessAddressSelector({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  const parsed = useMemo(() => parseStoredBusinessAddress(value), [value]);
  const [options, setOptions] = useState<DivisionOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const detail = parsed.data.detail || parsed.legacyText;

  const loadOptions = async () => {
    if (options.length || loading) return;
    setLoading(true);
    setLoadError("");
    try {
      const divisionModule = await import("@province-city-china/level");
      setOptions(
        (divisionModule.default as readonly DivisionNode[])
          .filter((node) => !NON_MAINLAND_CODES.has(node.code))
          .map(toOption),
      );
    } catch {
      setLoadError("行政区划暂时无法加载，请稍后重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Space direction="vertical" size={10} style={{ width: "100%" }}>
      <Cascader
        aria-label="主体地址省市区县"
        value={parsed.data.path.map((node) => node.code)}
        disabled={disabled}
        changeOnSelect
        showSearch
        options={options}
        placeholder={loading ? "正在加载行政区划…" : "选择省 / 市 / 区县"}
        style={{ width: "100%" }}
        onChange={(codes, selectedOptions) => {
          const path = selectedOptions.map((option) => ({
            code: String(option.value),
            name: String(option.label),
          }));
          onChange(serializeAddress({ version: 1, path, detail }));
        }}
        onOpenChange={(open) => {
          if (open) void loadOptions();
        }}
      />
      <Input
        aria-label="主体详细地址"
        value={detail}
        disabled={disabled}
        placeholder="请输入街道、路名、门牌号等详细地址"
        onChange={(event) =>
          onChange(
            serializeAddress({
              version: 1,
              path: parsed.data.path,
              detail: event.target.value,
            }),
          )
        }
      />
      {parsed.legacyText && (
        <Alert
          type="info"
          showIcon
          message="原地址已保留"
          description="请补选省、市和区县后再保存，原详细地址可继续编辑。"
        />
      )}
      {loadError && <Alert type="warning" showIcon message={loadError} />}
      <Typography.Text type="secondary">
        填写营业执照注册地址或当前实际经营地址；最低必须选择到市，区 / 县可进一步补充。
      </Typography.Text>
    </Space>
  );
}
