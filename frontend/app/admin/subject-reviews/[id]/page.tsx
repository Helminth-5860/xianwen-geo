"use client";

import { Alert, Button, Card, Descriptions, Input, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  approveSubjectReview,
  getSubjectReview,
  rejectSubjectReview,
  type SubjectReview,
} from "@/lib/subject-risk-client";

export default function SubjectReviewDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [review, setReview] = useState<SubjectReview | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const canReview = capabilities?.permission_keys.includes("subject_reviews.review") ?? false;

  useEffect(() => {
    void getSubjectReview(id)
      .then(setReview)
      .catch((failure) => setError(userMessage(failure)));
  }, [id]);

  const decide = async (decision: "approve" | "reject") => {
    if (!review) return;
    if (decision === "reject" && !reason.trim()) {
      setError("\u62d2\u7edd\u65f6\u5fc5\u987b\u586b\u5199\u539f\u56e0");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated =
        decision === "approve"
          ? await approveSubjectReview(review, reason)
          : await rejectSubjectReview(review, reason);
      setReview(updated);
    } catch (failure) {
      setError(userMessage(failure));
    } finally {
      setBusy(false);
    }
  };

  if (!review && !error) return <Typography.Text>{"\u6b63\u5728\u52a0\u8f7d"}</Typography.Text>;

  return (
    <main className="admin-page">
      <Typography.Title>{"\u4e3b\u4f53\u5ba1\u6838\u8be6\u60c5"}</Typography.Title>
      <Link href="/admin/subject-reviews">{"\u8fd4\u56de\u5ba1\u6838\u5217\u8868"}</Link>
      {error && <Alert type="error" showIcon message={error} />}
      {review && (
        <>
          <Descriptions bordered column={1}>
            <Descriptions.Item label={"\u4e3b\u4f53"}>{review.official_name}</Descriptions.Item>
            <Descriptions.Item label={"\u8d44\u6599\u7248\u672c"}>
              {review.version_no}
            </Descriptions.Item>
            <Descriptions.Item label={"\u72b6\u6001"}>
              <Tag>{review.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label={"\u547d\u4e2d\u539f\u56e0"}>
              {review.reason_types.join(", ")}
            </Descriptions.Item>
          </Descriptions>
          {review.status === "pending" && (
            <Card title={"\u5ba1\u6838\u51b3\u7b56"}>
              {!canReview && (
                <Alert
                  type="info"
                  message={"\u5f53\u524d\u8d26\u53f7\u65e0\u4e3b\u4f53\u5ba1\u6838\u6743\u9650"}
                />
              )}
              <Input.TextArea
                aria-label={"\u5ba1\u6838\u539f\u56e0"}
                value={reason}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
                disabled={!canReview || busy}
              />
              <Space>
                <Button
                  type="primary"
                  disabled={!canReview || busy}
                  onClick={() => void decide("approve")}
                >
                  {"\u901a\u8fc7"}
                </Button>
                <Button danger disabled={!canReview || busy} onClick={() => void decide("reject")}>
                  {"\u62d2\u7edd"}
                </Button>
              </Space>
            </Card>
          )}
        </>
      )}
    </main>
  );
}
