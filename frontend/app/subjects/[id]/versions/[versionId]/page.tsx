"use client";

import { Alert, Card, Descriptions, List, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getSubjectVersion, type SubjectVersionDetail } from "@/lib/subjects-client";

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
    return <Spin fullscreen description={"\u6b63\u5728\u52a0\u8f7d\u7248\u672c\u8be6\u60c5"} />;
  }

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}/versions`}>{"\u8fd4\u56de\u7248\u672c\u5386\u53f2"}</Link>
      {error && <Alert type="error" showIcon message={error} />}
      {version && (
        <>
          <Typography.Title>{`v${version.version_no} \u00b7 ${version.official_name}`}</Typography.Title>
          <Typography.Paragraph type="secondary">
            {
              "\u4ee5\u4e0b\u5185\u5bb9\u4f7f\u7528\u8be5\u7248\u672c\u81ea\u5df1\u4fdd\u5b58\u7684\u51bb\u7ed3 Schema \u5c55\u793a\u3002"
            }
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
          <Card title={"\u540d\u79f0\u8bed\u4e49"} style={{ marginTop: 20 }}>
            <List
              dataSource={[...version.names]}
              renderItem={(name) => (
                <List.Item>
                  <Tag>{name.role}</Tag>
                  {name.display_value}
                </List.Item>
              )}
            />
          </Card>
          <Card title={"\u4ea7\u54c1\u786e\u8ba4"} style={{ marginTop: 20 }}>
            <List
              locale={{ emptyText: "\u65e0\u4ea7\u54c1\u5019\u9009" }}
              dataSource={[...version.products]}
              renderItem={(product) => (
                <List.Item>
                  <Typography.Text>{product.display_value}</Typography.Text>
                  <span>
                    <Tag color={product.uniqueness_confirmed ? "green" : "default"}>
                      {product.uniqueness_confirmed
                        ? "\u5df2\u786e\u8ba4\u552f\u4e00"
                        : "\u672a\u786e\u8ba4\u552f\u4e00"}
                    </Tag>
                    {product.include_in_mention && (
                      <Tag color="blue">{"\u52a0\u5165\u63d0\u53ca\u8bcd"}</Tag>
                    )}
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
