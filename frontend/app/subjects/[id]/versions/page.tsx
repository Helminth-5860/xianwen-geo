"use client";

import { Alert, Card, List, Spin, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getSubjectVersions, type SubjectVersionSummary } from "@/lib/subjects-client";

export default function SubjectVersionsPage() {
  const params = useParams<{ id: string }>();
  const [versions, setVersions] = useState<SubjectVersionSummary[]>();
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    void getSubjectVersions(params.id)
      .then((data) => {
        if (current) setVersions(data.versions);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [params.id]);

  if (!versions && !error) {
    return <Spin fullscreen description={"\u6b63\u5728\u52a0\u8f7d\u6b63\u5f0f\u7248\u672c"} />;
  }

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}`}>{"\u8fd4\u56de\u4e3b\u4f53\u8be6\u60c5"}</Link>
      <Typography.Title>{"\u6b63\u5f0f\u7248\u672c\u5386\u53f2"}</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      {versions && (
        <Card>
          <List
            locale={{ emptyText: "\u5c1a\u65e0\u6b63\u5f0f\u7248\u672c" }}
            dataSource={versions}
            renderItem={(version) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Link href={`/subjects/${params.id}/versions/${version.id}`}>
                      {`v${version.version_no} \u00b7 ${version.official_name}`}
                    </Link>
                  }
                  description={new Date(version.created_at).toLocaleString("zh-CN")}
                />
              </List.Item>
            )}
          />
        </Card>
      )}
    </main>
  );
}
