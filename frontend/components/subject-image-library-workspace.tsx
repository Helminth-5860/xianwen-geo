"use client";

import { Alert, Button, Card, Empty, Image, List, Pagination, Space, Tag, Typography } from "antd";
import { useEffect, useMemo, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { createImageBatchDownload, getSubjectImages, type ImageAsset } from "@/lib/images-client";

const PAGE_SIZE = 20;
const EMPTY_IMAGES: ImageAsset[] = [];

const IMAGE_ROLE_LABEL: Readonly<Record<ImageAsset["role"], string>> = {
  cover: "文章封面",
  illustration: "正文插图",
  channel: "渠道图片",
};

type Props = Readonly<{ subjectId: string }>;

export function SubjectImageLibraryWorkspace({ subjectId }: Props) {
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadedSubjectId, setLoadedSubjectId] = useState("");

  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const result = await getSubjectImages(subjectId, true);
        if (active) {
          setImages(result.results);
          setSelectedIds([]);
          setPage(1);
          setLoadedSubjectId(subjectId);
        }
      } catch (reason) {
        if (active) {
          setImages([]);
          setError(userMessage(reason));
          setLoadedSubjectId(subjectId);
        }
      } finally {
        if (active) setLoading(false);
      }
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [subjectId]);

  const visibleImages = loadedSubjectId === subjectId ? images : EMPTY_IMAGES;
  const pageImages = useMemo(
    () => visibleImages.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [page, visibleImages],
  );

  const batchDownload = async () => {
    setError("");
    try {
      const result = await createImageBatchDownload(subjectId, selectedIds);
      window.location.assign(result.url);
    } catch (reason) {
      setError(userMessage(reason));
    }
  };

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Typography.Title level={2}>主体图片库</Typography.Title>
        <Typography.Text type="secondary">
          查看和管理已保存到当前主体图库的图片，每页显示 20 张。
        </Typography.Text>
        {error && <Alert type="error" showIcon title={error} />}
        <Card title={`已保存图片 ${visibleImages.length} 张`}>
          <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
            <List
              loading={loading || loadedSubjectId !== subjectId}
              grid={{ gutter: 12, xs: 1, sm: 2, md: 3 }}
              dataSource={pageImages}
              locale={{
                emptyText: (
                  <Empty description="还没有图片，生成并保存后会出现在这里。">
                    <Button type="primary" href={`/subjects/${subjectId}/images`}>
                      生成第一张图片
                    </Button>
                  </Empty>
                ),
              }}
              renderItem={(image) => (
                <List.Item>
                  <Card
                    size="small"
                    cover={
                      image.url ? (
                        <Image
                          src={image.url}
                          alt="主体图片"
                          height={140}
                          style={{ objectFit: "cover" }}
                        />
                      ) : undefined
                    }
                  >
                    <Space orientation="vertical">
                      <Space>
                        <input
                          aria-label={`选择${IMAGE_ROLE_LABEL[image.role]}图片`}
                          type="checkbox"
                          checked={selectedIds.includes(image.id)}
                          onChange={(event) =>
                            setSelectedIds((current) =>
                              event.target.checked
                                ? [...current, image.id]
                                : current.filter((id) => id !== image.id),
                            )
                          }
                        />
                        <Tag>{IMAGE_ROLE_LABEL[image.role]}</Tag>
                        <Tag color="green">已保存</Tag>
                      </Space>
                      <Typography.Text type="secondary">
                        {image.width}×{image.height}
                      </Typography.Text>
                    </Space>
                  </Card>
                </List.Item>
              )}
            />
            <Space wrap>
              <Button
                disabled={loadedSubjectId !== subjectId || !selectedIds.length}
                onClick={batchDownload}
              >
                批量下载原图压缩包
              </Button>
              {visibleImages.length > PAGE_SIZE && (
                <Pagination
                  aria-label="主体图片库分页"
                  current={page}
                  pageSize={PAGE_SIZE}
                  total={visibleImages.length}
                  showSizeChanger={false}
                  onChange={setPage}
                />
              )}
            </Space>
          </Space>
        </Card>
      </Space>
    </main>
  );
}
