"use client";

import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExportOutlined,
  PhoneOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Pagination,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
  type TableProps,
} from "antd";
import { useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { userMessage } from "@/lib/auth-client";
import {
  getAdminPaidMediaInquiries,
  updateAdminPaidMediaInquiry,
  type AdminPaidMediaInquiry,
} from "@/lib/paid-media-client";

const { Paragraph, Text } = Typography;
const PAGE_SIZE = 20;

const statusPresentation: Readonly<
  Record<AdminPaidMediaInquiry["status"], Readonly<{ label: string; color: string }>>
> = {
  pending: { label: "待联系", color: "gold" },
  contacted: { label: "已联系", color: "blue" },
  completed: { label: "已完成", color: "green" },
  cancelled: { label: "已取消", color: "default" },
};

function formatMoney(value: string) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "价格待确认";
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export default function AdminPaidMediaInquiriesPage() {
  const [messageApi, messageHolder] = message.useMessage();
  const [items, setItems] = useState<AdminPaidMediaInquiry[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [status, setStatus] = useState("");
  const [loadedRequestKey, setLoadedRequestKey] = useState("");
  const [updatingId, setUpdatingId] = useState("");
  const [selected, setSelected] = useState<AdminPaidMediaInquiry | null>(null);
  const requestKey = `${debouncedQuery}\u0000${status}\u0000${page}`;
  const loading = loadedRequestKey !== requestKey;

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const controller = new AbortController();
    void getAdminPaidMediaInquiries({
      page,
      status,
      search: debouncedQuery,
      signal: controller.signal,
    })
      .then((response) => {
        setItems(response.items);
        setTotal(response.pagination.count);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        messageApi.error(userMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedRequestKey(requestKey);
      });
    return () => controller.abort();
  }, [debouncedQuery, messageApi, page, requestKey, status]);

  const updateStatus = async (
    inquiry: AdminPaidMediaInquiry,
    nextStatus: "contacted" | "cancelled" | "completed",
  ) => {
    setUpdatingId(inquiry.id);
    try {
      const updated = await updateAdminPaidMediaInquiry(inquiry.id, nextStatus, inquiry.version);
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelected((current) => (current?.id === updated.id ? updated : current));
      messageApi.success(
        nextStatus === "contacted"
          ? "已标记为已联系"
          : nextStatus === "completed"
            ? "媒体发布需求已完成"
            : "媒体发布需求已取消",
      );
    } catch (reason) {
      messageApi.error(userMessage(reason));
    } finally {
      setUpdatingId("");
    }
  };

  const columns: TableProps<AdminPaidMediaInquiry>["columns"] = [
    {
      title: "客户",
      key: "user",
      render: (_, inquiry) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{inquiry.user.nickname}</Text>
          <Text type="secondary">
            <PhoneOutlined aria-hidden="true" /> {inquiry.user.phone}
          </Text>
        </Space>
      ),
    },
    {
      title: "当前主体",
      dataIndex: ["subject", "name"],
      key: "subject",
    },
    {
      title: "媒体",
      dataIndex: "item_count",
      key: "item_count",
      render: (count: number) => `${count} 家`,
    },
    {
      title: "当前合计",
      dataIndex: "total_price",
      key: "total_price",
      render: (value: string) => <Text strong>{formatMoney(value)}</Text>,
    },
    {
      title: "提交时间",
      dataIndex: "created_at",
      key: "created_at",
      render: (value: string) => new Date(value).toLocaleString("zh-CN"),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (value: AdminPaidMediaInquiry["status"]) => (
        <Tag color={statusPresentation[value].color}>{statusPresentation[value].label}</Tag>
      ),
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 260,
      render: (_, inquiry) => (
        <Space wrap>
          <Button onClick={() => setSelected(inquiry)}>查看明细</Button>
          {inquiry.status === "pending" ? (
            <Button
              type="primary"
              loading={updatingId === inquiry.id}
              onClick={() => void updateStatus(inquiry, "contacted")}
            >
              标记已联系
            </Button>
          ) : null}
          {inquiry.status === "contacted" ? (
            <Button
              icon={<CheckCircleOutlined aria-hidden="true" />}
              loading={updatingId === inquiry.id}
              onClick={() => void updateStatus(inquiry, "completed")}
            >
              标记已完成
            </Button>
          ) : null}
          {!["completed", "cancelled"].includes(inquiry.status) ? (
            <Popconfirm
              title="确认取消该媒体发布需求？"
              okText="确认取消"
              cancelText="暂不取消"
              onConfirm={() => void updateStatus(inquiry, "cancelled")}
            >
              <Button danger icon={<CloseCircleOutlined aria-hidden="true" />}>
                标记已取消
              </Button>
            </Popconfirm>
          ) : null}
        </Space>
      ),
    },
  ];

  return (
    <div className="admin-page">
      {messageHolder}
      <AdminPageHeader
        title="媒体发布需求"
        description="查看客户选择的付费媒体，联系客户确认档期、发布安排和最终费用。"
      />

      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Space wrap size="middle" style={{ width: "100%" }}>
          <Input
            style={{ width: 360, maxWidth: "100%" }}
            prefix={<SearchOutlined aria-hidden="true" />}
            value={query}
            placeholder="搜索用户、手机号或主体名称"
            aria-label="搜索媒体发布需求"
            allowClear
            onChange={(event) => {
              setQuery(event.target.value);
              setPage(1);
            }}
          />
          <Select
            style={{ width: 160 }}
            aria-label="按处理状态筛选"
            value={status}
            options={[
              { value: "", label: "全部状态" },
              { value: "pending", label: "待联系" },
              { value: "contacted", label: "已联系" },
              { value: "completed", label: "已完成" },
              { value: "cancelled", label: "已取消" },
            ]}
            onChange={(value) => {
              setStatus(value);
              setPage(1);
            }}
          />
        </Space>
      </Card>

      <Card className="admin-surface">
        <Spin spinning={loading}>
          {items.length > 0 ? (
            <>
              <Table
                rowKey="id"
                columns={columns}
                dataSource={items}
                pagination={false}
                scroll={{ x: 1120 }}
              />
              {total > PAGE_SIZE ? (
                <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 18 }}>
                  <Pagination
                    aria-label="媒体发布需求分页"
                    current={page}
                    pageSize={PAGE_SIZE}
                    total={total}
                    showSizeChanger={false}
                    showTotal={(count) => `共 ${count} 条需求`}
                    onChange={setPage}
                  />
                </div>
              ) : null}
            </>
          ) : loading ? null : (
            <Empty description="暂无符合条件的媒体发布需求" />
          )}
        </Spin>
      </Card>

      <Modal
        width={720}
        open={selected !== null}
        title="媒体发布需求明细"
        footer={<Button onClick={() => setSelected(null)}>关闭</Button>}
        onCancel={() => setSelected(null)}
      >
        {selected ? (
          <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
            <Paragraph>
              {selected.user.nickname}　{selected.user.phone}　·　{selected.subject.name}
            </Paragraph>
            <InquirySummary inquiry={selected} />
            <div style={{ maxHeight: 420, overflow: "auto" }}>
              {selected.selected_media.map((media) => (
                <Card key={media.id} size="small" style={{ marginBottom: 8 }}>
                  <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
                    {media.url ? (
                      <a href={media.url} target="_blank" rel="noopener noreferrer">
                        {media.name} <ExportOutlined aria-hidden="true" />
                      </a>
                    ) : (
                      <Text strong>{media.name}</Text>
                    )}
                    <Text strong>{formatMoney(media.price)}</Text>
                  </Space>
                  <br />
                  <Text type="secondary">{media.domain || "暂无可用链接"}</Text>
                </Card>
              ))}
            </div>
          </Space>
        ) : null}
      </Modal>
    </div>
  );
}

function InquirySummary({ inquiry }: Readonly<{ inquiry: AdminPaidMediaInquiry }>) {
  return (
    <Card size="small">
      <Space wrap style={{ width: "100%", justifyContent: "space-between" }}>
        <Text>已选 {inquiry.item_count} 家媒体</Text>
        <Text strong>当前合计 {formatMoney(inquiry.total_price)}</Text>
        <Tag color={statusPresentation[inquiry.status].color}>
          {statusPresentation[inquiry.status].label}
        </Tag>
      </Space>
    </Card>
  );
}
