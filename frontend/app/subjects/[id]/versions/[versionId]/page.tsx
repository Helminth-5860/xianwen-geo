"use client";

import { Alert, Card, Descriptions, List, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getSubjectVersion, type SubjectVersionDetail } from "@/lib/subjects-client";

const nameRoleLabels: Readonly<Record<SubjectVersionDetail["names"][number]["role"], string>> = {
  official_name: "主体名称",
  alias: "常用名称",
  english_name: "英文名称",
};

function displayValue(
  value: unknown,
  options: ReadonlyArray<{ option_key: string; label: string }>,
) {
  const labels = new Map(options.map((option) => [option.option_key, option.label]));
  if (Array.isArray(value))
    return value.map((item) => labels.get(String(item)) ?? String(item)).join("\u3001");
  if (typeof value === "string") return labels.get(value) ?? value;
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

export default function SubjectVersionDetailPage() {
  const params = useParams<{ id: string; versionId: string }>();
  const [version, setVersion] = useState<SubjectVersionDetail>();
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    void getSubjectVersion(params.id, params.versionId)
      .then((data) => {
        if (current) setVersion(data);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [params.id, params.versionId]);

  if (!version && !error) {
    return <Spin fullscreen description="正在加载资料记录" />;
  }

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}/versions`}>返回资料更新记录</Link>
      {error && <Alert type="error" showIcon message={error} />}
      {version && (
        <>
          <Typography.Title>{`${version.official_name} · 第 ${version.version_no} 次保存`}</Typography.Title>
          <Typography.Paragraph type="secondary">
            这里展示该次保存时的主体资料，之后的修改不会影响这份记录。
          </Typography.Paragraph>
          <Card title={version.form_schema.name}>
            <Descriptions column={1} bordered>
              {version.form_schema.fields.map((field) => (
                <Descriptions.Item key={field.field_key} label={field.label}>
                  {displayValue(version.field_values[field.field_key], field.options)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </Card>
          <Card title="主体名称" style={{ marginTop: 20 }}>
            <List
              dataSource={[...version.names]}
              renderItem={(name) => (
                <List.Item>
                  <Tag>{nameRoleLabels[name.role]}</Tag>
                  {name.display_value}
                </List.Item>
              )}
            />
          </Card>
          <Card title="产品与服务" style={{ marginTop: 20 }}>
            <List
              locale={{ emptyText: "该次保存未记录产品或服务" }}
              dataSource={[...version.products]}
              renderItem={(product) => (
                <List.Item>
                  <Typography.Text>{product.display_value}</Typography.Text>
                  <span>
                    <Tag color={product.uniqueness_confirmed ? "green" : "default"}>
                      {product.uniqueness_confirmed ? "名称已确认" : "名称待确认"}
                    </Tag>
                    {product.include_in_mention && <Tag color="blue">用于品牌提及分析</Tag>}
                  </span>
                </List.Item>
              )}
            />
          </Card>
        </>
      )}
    </main>
  );
}
