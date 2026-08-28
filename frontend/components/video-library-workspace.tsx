"use client";

import { Alert, Button, Card, Empty, List, Pagination, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import {
  createVideoDownloadIntent,
  listSubjectVideos,
  videoUserMessage,
  type VideoAsset,
  type VideoPagination,
} from "@/lib/videos-client";

type Props = Readonly<{ subjectId: string }>;

const PAGE_SIZE = 20;
const EMPTY_PAGINATION: VideoPagination = {
  page: 1,
  page_size: PAGE_SIZE,
  count: 0,
  total_pages: 0,
};

export function VideoLibraryWorkspace({ subjectId }: Props) {
  const [videos, setVideos] = useState<VideoAsset[]>([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<VideoPagination>(EMPTY_PAGINATION);
  const [loadedSubjectId, setLoadedSubjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyVideoId, setBusyVideoId] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      setError("");
      try {
        const result = await listSubjectVideos(subjectId, page, PAGE_SIZE, signal);
        if (signal?.aborted) return;
        setVideos(result.items);
        setPagination(result.pagination);
        setLoadedSubjectId(subjectId);
      } catch (reason) {
        if (signal?.aborted) return;
        setVideos([]);
        setLoadedSubjectId(subjectId);
        setError(videoUserMessage(reason));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [page, subjectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [load]);

  const visibleVideos = loadedSubjectId === subjectId ? videos : [];

  const download = async (video: VideoAsset) => {
    setBusyVideoId(video.id);
    setError("");
    try {
      const result = await createVideoDownloadIntent(video.job_id);
      window.location.assign(result.url);
    } catch (reason) {
      setError(videoUserMessage(reason));
    } finally {
      setBusyVideoId("");
    }
  };

  return (
    <main className="page-shell" data-subject-id={subjectId}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2}>视频库</Typography.Title>
          <Typography.Text type="secondary">
            查看和下载已保存到当前主体的视频，每页显示 20 条
          </Typography.Text>
        </div>
        <Alert
          type="info"
          showIcon
          title="视频仅对当前主体可见"
          description="生成的视频需要由你明确保存后才会出现在这里。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        <Card title={`已保存视频 ${pagination.count} 条`}>
          <List
            loading={loading || loadedSubjectId !== subjectId}
            dataSource={visibleVideos}
            locale={{
              emptyText: (
                <Empty description="当前主体还没有已保存的视频。">
                  <Button type="primary" href={`/subjects/${subjectId}/videos/new`}>
                    生成第一个视频
                  </Button>
                </Empty>
              ),
            }}
            renderItem={(video) => (
              <List.Item
                actions={[
                  <Button
                    key="download"
                    loading={busyVideoId === video.id}
                    disabled={Boolean(busyVideoId)}
                    onClick={() => void download(video)}
                  >
                    下载
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  avatar={
                    video.url ? (
                      <video
                        src={video.url}
                        controls
                        preload="metadata"
                        aria-label="视频库预览"
                        style={{
                          width: 220,
                          maxWidth: "38vw",
                          borderRadius: 8,
                          background: "#111827",
                        }}
                      />
                    ) : undefined
                  }
                  title={`视频 · ${video.duration_seconds} 秒`}
                  description={
                    <Space wrap>
                      <Tag>{video.aspect_ratio}</Tag>
                      <Tag>720P</Tag>
                      <Typography.Text type="secondary">
                        保存于{" "}
                        {new Date(video.created_at).toLocaleString("zh-CN", { hour12: false })}
                      </Typography.Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
          {pagination.count > PAGE_SIZE && (
            <Pagination
              aria-label="视频库分页"
              current={page}
              pageSize={PAGE_SIZE}
              total={pagination.count}
              showSizeChanger={false}
              onChange={setPage}
            />
          )}
        </Card>
      </Space>
    </main>
  );
}
