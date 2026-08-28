import { Button, Result, Space } from "antd";

export default function NotFoundPage() {
  return (
    <main className="page-shell">
      <Result
        status="warning"
        title="未找到这个页面"
        subTitle="页面可能已移动或删除。你可以返回工作台，或进入主体档案继续使用。"
        extra={
          <Space wrap>
            <Button type="primary" href="/workspace">
              返回工作台
            </Button>
            <Button href="/subjects">进入主体档案</Button>
          </Space>
        }
      />
    </main>
  );
}
