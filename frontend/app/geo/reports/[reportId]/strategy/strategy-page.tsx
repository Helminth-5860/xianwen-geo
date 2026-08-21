"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  InputNumber,
  List,
  Radio,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  createStrategy,
  getStrategies,
  getStrategy,
  saveStrategyNote,
  type Strategy,
  type StrategyList,
  type StrategyPeriod,
} from "@/lib/strategy-assistant-client";

export const STRATEGY_POLL_INTERVAL_MS = 1200;

export default function ImprovementStrategyPage({ reportId }: Readonly<{ reportId: string }>) {
  const [data, setData] = useState<StrategyList>();
  const [selected, setSelected] = useState<Strategy>();
  const [period, setPeriod] = useState<StrategyPeriod>("30d");
  const [customDays, setCustomDays] = useState(14);
  const [note, setNote] = useState("");
  const [noteVersion, setNoteVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await getStrategies(reportId);
      setData(next);
      setSelected((current) => {
        const replacement = next.items.find((item) => item.id === current?.id) ?? next.items[0];
        return replacement;
      });
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [reportId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setNote(selected?.note?.text ?? "");
      setNoteVersion(selected?.note?.version ?? 0);
    }, 0);
    return () => window.clearTimeout(timer);
  }, [selected]);

  useEffect(() => {
    if (!selected || !["queued", "running"].includes(selected.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getStrategy(selected.id);
        setSelected(next);
        if (["succeeded", "failed"].includes(next.status)) await load();
      } catch (reason) {
        setError(userMessage(reason));
      }
    }, STRATEGY_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [load, selected]);

  const generate = async () => {
    if (!data) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const next = await createStrategy(
        reportId,
        {
          period,
          ...(period === "custom" ? { custom_days: customDays } : {}),
          regenerate: !data.first_free_available,
        },
        crypto.randomUUID(),
      );
      setSelected(next);
      setNotice(
        data.first_free_available ? "首份免费策略已提交" : "重新生成已提交，成功后扣除 1 次",
      );
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const saveNote = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const saved = await saveStrategyNote(selected.id, note, noteVersion);
      setNoteVersion(saved.version);
      setSelected({ ...selected, note: saved });
      setNotice("个人备注已保存");
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!data && !error) return <Spin fullscreen description="正在加载改善策略" />;

  const generating = Boolean(selected && ["queued", "running"].includes(selected.status));

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>GEO 改善策略</Typography.Title>
          <Button href={`/geo/reports/${reportId}`}>返回报告</Button>
        </Space>
        <Alert
          type="info"
          showIcon
          title="策略是基于不可修改报告事实生成的建议，不会重新检测或评分，也不会执行任务。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}

        <Card title="生成设置">
          <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
            <Radio.Group
              aria-label="策略周期"
              value={period}
              onChange={(event) => setPeriod(event.target.value as StrategyPeriod)}
              options={[
                { label: "7 天", value: "7d" },
                { label: "30 天", value: "30d" },
                { label: "90 天", value: "90d" },
                { label: "自定义", value: "custom" },
              ]}
            />
            {period === "custom" && (
              <InputNumber
                aria-label="自定义天数"
                min={1}
                max={365}
                value={customDays}
                onChange={(value) => setCustomDays(value ?? 14)}
              />
            )}
            <Space wrap>
              <Tag color={data?.first_free_available ? "green" : "blue"}>
                {data?.first_free_available ? "首份策略免费" : "已使用首份免费策略"}
              </Tag>
              <Typography.Text>
                剩余重新生成次数：{data?.remaining_regenerations ?? "当前不可用"}
              </Typography.Text>
              <Button type="primary" loading={busy || generating} onClick={() => void generate()}>
                {data?.first_free_available ? "生成策略" : "重新生成策略"}
              </Button>
            </Space>
            {!data?.first_free_available && (
              <Typography.Text type="secondary">
                只有成功生成新版本才扣除次数；失败会释放冻结额度并保留全部历史结果。
              </Typography.Text>
            )}
          </Space>
        </Card>

        {generating && <Spin description="DeepSeek 正在生成策略" />}
        {selected?.status === "failed" && (
          <Alert type="error" showIcon title={`策略生成失败：${selected.safe_error_code}`} />
        )}
        {selected?.status === "succeeded" && selected.body && (
          <>
            <Card title="AI 原始策略（不可编辑）">
              <Space orientation="vertical" size="large" style={{ width: "100%" }}>
                <Typography.Paragraph>{selected.body.overview}</Typography.Paragraph>
                <Typography.Title level={4}>优先事项</Typography.Title>
                <List
                  dataSource={[...selected.body.priorities]}
                  renderItem={(item) => (
                    <List.Item>
                      <List.Item.Meta
                        title={item.title}
                        description={
                          <Space orientation="vertical">
                            <Typography.Text>{item.rationale}</Typography.Text>
                            <ul>
                              {item.actions.map((action) => (
                                <li key={action}>{action}</li>
                              ))}
                            </ul>
                            <Typography.Text type="secondary">
                              成功指标：{item.success_metric}
                            </Typography.Text>
                          </Space>
                        }
                      />
                    </List.Item>
                  )}
                />
                <Typography.Title level={4}>阶段安排</Typography.Title>
                <Row gutter={[16, 16]}>
                  {selected.body.schedule.map((item) => (
                    <Col xs={24} md={12} key={`${item.phase}-${item.focus}`}>
                      <Card size="small" title={item.phase}>
                        <Typography.Paragraph>{item.focus}</Typography.Paragraph>
                        <ul>
                          {item.actions.map((action) => (
                            <li key={action}>{action}</li>
                          ))}
                        </ul>
                      </Card>
                    </Col>
                  ))}
                </Row>
              </Space>
            </Card>

            <Card title="推荐文章主题">
              <List
                dataSource={[...selected.body.article_topics]}
                renderItem={(topic) => (
                  <List.Item
                    actions={[
                      <Link key={topic.route} href={topic.route}>
                        带主题进入文章页
                      </Link>,
                    ]}
                  >
                    <List.Item.Meta title={topic.title} description={topic.reason} />
                  </List.Item>
                )}
              />
              <Typography.Text type="secondary">
                此处只传递主题意图；进入页面不会自动生成文章或扣除文章额度。
              </Typography.Text>
            </Card>

            <Card title="我的备注（独立可编辑）">
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Input.TextArea
                  aria-label="个人备注"
                  rows={5}
                  maxLength={10000}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                />
                <Button loading={busy} onClick={() => void saveNote()}>
                  保存备注
                </Button>
              </Space>
            </Card>
          </>
        )}

        <Card title="历史策略版本">
          <List
            locale={{ emptyText: "尚未生成策略" }}
            dataSource={data?.items ?? []}
            renderItem={(item) => (
              <List.Item
                onClick={() => setSelected(item)}
                style={{ cursor: "pointer" }}
                actions={[<Button key={item.id}>查看</Button>]}
              >
                <List.Item.Meta
                  title={`${item.period_days} 天策略 · ${item.status}`}
                  description={`${item.billing.first_free ? "首次免费" : "重新生成"} · ${item.created_at}`}
                />
              </List.Item>
            )}
          />
        </Card>
      </Space>
    </main>
  );
}
