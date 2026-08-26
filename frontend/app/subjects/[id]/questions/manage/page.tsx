"use client";

import { Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";

import QuestionManagementPanel from "../question-management-panel";

export default function SubjectQuestionManagementPage() {
  const params = useParams<{ id: string }>();
  const { currentSubject, subjects } = useSubjectWorkspace();
  const subject = subjects.find((item) => item.id === params.id) ?? currentSubject;

  return (
    <main className="page-shell">
      <Link href={`/subjects/${params.id}`}>返回主体详情</Link>
      <Typography.Title style={{ marginTop: 16 }}>问题管理</Typography.Title>
      <Typography.Paragraph type="secondary">查看当前正式问题库及参与检测状态</Typography.Paragraph>
      <Typography.Paragraph type="secondary">
        当前企业：{subject?.official_name || subject?.subject_type.name || "当前主体"}
      </Typography.Paragraph>
      <QuestionManagementPanel subjectId={params.id} />
    </main>
  );
}
