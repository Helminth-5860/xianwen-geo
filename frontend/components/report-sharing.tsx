"use client";

import { Alert, Button, Card, Input, InputNumber, List, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { REPORT_SHARE_STATUS_LABELS } from "@/lib/product-copy";
import {
  closeReportShare,
  createReportShare,
  getReportShares,
  getWhiteLabel,
  saveWhiteLabel,
  type ReportShare,
  type WhiteLabel,
} from "@/lib/report-sharing-client";

export function ReportSharing({
  reportId,
  subjectId,
}: Readonly<{ reportId: string; subjectId: string }>) {
  const [brand, setBrand] = useState<WhiteLabel>();
  const [shares, setShares] = useState<ReportShare[]>([]);
  const [brandName, setBrandName] = useState("显问 GEO");
  const [primaryColor, setPrimaryColor] = useState("#1677ff");
  const [password, setPassword] = useState("");
  const [days, setDays] = useState(30);
  const [createdUrl, setCreatedUrl] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextBrand, nextShares] = await Promise.all([
        getWhiteLabel(subjectId),
        getReportShares(reportId),
      ]);
      setBrand(nextBrand);
      setShares(nextShares.items);
      setBrandName(nextBrand.config?.brand_name ?? "显问 GEO");
      setPrimaryColor(nextBrand.config?.primary_color ?? "#1677ff");
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [reportId, subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const saveBrand = async () => {
    if (!brand) return;
    setBusy(true);
    try {
      const saved = await saveWhiteLabel(subjectId, {
        brand_name: brandName,
        primary_color: primaryColor,
        header_text: brand.config?.header_text ?? "",
        footer_text: brand.config?.footer_text ?? "",
        contact: brand.config?.contact ?? "",
        statement: brand.config?.statement ?? "",
        expected_version: brand.config?.version ?? 0,
      });
      setBrand(saved);
      setNotice("品牌展示设置已保存，新创建的报告分享将使用当前品牌信息。");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setBusy(true);
    try {
      const share = await createReportShare(reportId, password, days);
      setShares((current) => [share, ...current]);
      setCreatedUrl(share.url ?? "");
      setPassword("");
      setNotice("报告分享地址已创建。为保护报告内容，该地址只显示一次，请立即保存。");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="品牌展示与报告分享">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}
        <Alert
          type="info"
          title={
            brand?.enabled
              ? "当前套餐支持自定义报告品牌展示。"
              : "当前报告使用显问品牌展示；升级对应套餐后可自定义品牌。"
          }
        />
        {brand?.enabled && (
          <Space wrap>
            <Input
              aria-label="品牌名称"
              value={brandName}
              onChange={(event) => setBrandName(event.target.value)}
            />
            <Input
              aria-label="品牌主色"
              value={primaryColor}
              onChange={(event) => setPrimaryColor(event.target.value)}
            />
            <Button loading={busy} onClick={() => void saveBrand()}>
              保存品牌展示
            </Button>
          </Space>
        )}
        <Space wrap>
          <Input.Password
            aria-label="分享密码"
            value={password}
            placeholder="可选密码（至少 8 位）"
            onChange={(event) => setPassword(event.target.value)}
          />
          <InputNumber
            aria-label="分享有效天数"
            min={1}
            max={365}
            value={days}
            onChange={(value) => setDays(value ?? 30)}
          />
          <Button
            type="primary"
            loading={busy}
            disabled={Boolean(password && password.length < 8)}
            onClick={() => void create()}
          >
            创建完整报告分享
          </Button>
        </Space>
        {createdUrl && (
          <Alert
            type="warning"
            title="请立即保存分享地址"
            description={
              <Typography.Text copyable={{ text: `${window.location.origin}${createdUrl}` }}>
                {`${window.location.origin}${createdUrl}`}
              </Typography.Text>
            }
          />
        )}
        <List
          dataSource={shares}
          locale={{ emptyText: "暂时没有报告分享。创建后，可在这里查看访问情况。" }}
          renderItem={(share) => (
            <List.Item
              actions={[
                <Button
                  key={share.id}
                  danger
                  disabled={share.status !== "active"}
                  onClick={async () => {
                    const closed = await closeReportShare(share.id);
                    setShares((current) =>
                      current.map((item) => (item.id === closed.id ? closed : item)),
                    );
                  }}
                >
                  关闭
                </Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Tag>{REPORT_SHARE_STATUS_LABELS[share.status]}</Tag>
                    {share.password_required && <Tag color="blue">密码保护</Tag>}
                  </Space>
                }
                description={`访问 ${share.access_count} 次 · 有效期 ${share.expires_at ?? "长期"}`}
              />
            </List.Item>
          )}
        />
      </Space>
    </Card>
  );
}
