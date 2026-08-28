"use client";

import { Button, Result, Space } from "antd";

export default function GlobalErrorPage({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <main className="page-shell">
      <Result
        status="error"
        title="页面暂时无法打开"
        subTitle="你的数据不会受到影响。可以重新尝试，或先返回工作台继续使用其他功能。"
        extra={
          <Space wrap>
            <Button type="primary" onClick={reset}>
              重新尝试
            </Button>
            <Button href="/workspace">返回工作台</Button>
          </Space>
        }
      />
    </main>
  );
}
