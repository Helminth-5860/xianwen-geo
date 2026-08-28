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
    return <Spin fullscreen description="正在加载资料更新记录" />;
  }

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}`}>{"\u8fd4\u56de\u4e3b\u4f53\u8be6\u60c5"}</Link>
      <Typography.Title>资料更新记录</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      {versions && (
        <Card>
          <List
            locale={{ emptyText: "暂无更新记录，保存主体资料后会显示在这里" }}
            dataSource={versions}
            renderItem={(version) => (
              <List.Item>
                <List.Item.Meta
                  title={
                    <Link href={`/subjects/${params.id}/versions/${version.id}`}>
                      {`第 ${version.version_no} 次保存 · ${version.official_name}`}
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
