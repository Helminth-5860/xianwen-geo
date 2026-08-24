"use client";

import { InfoCircleOutlined, SaveOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Input, Switch, Upload } from "antd";

import { AdminPageHeader } from "@/components/admin/admin-page-header";

export default function AdminSettingsPage() {
  return (
    <div className="admin-page">
      <AdminPageHeader
        title="系统设置"
        description="维护平台名称、品牌展示、注册入口和全站公告等基础信息。"
        actions={
          <Button type="primary" icon={<SaveOutlined />} disabled>
            保存设置
          </Button>
        }
      />
      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        title="设置保存接口尚未接通"
        description="当前页面先提供企业级设置结构，不会伪造保存结果。"
        style={{ marginBottom: 18 }}
      />
      <Card className="admin-surface" title="品牌信息">
        <Form layout="vertical" disabled initialValues={{ platformName: "显问 GEO 智能体系统" }}>
          <Form.Item label="平台名称" name="platformName">
            <Input />
          </Form.Item>
          <Form.Item label="平台 Logo">
            <Upload disabled>
              <Button>选择图片</Button>
            </Upload>
          </Form.Item>
          <Form.Item label="登录页介绍" name="loginDescription">
            <Input.TextArea rows={3} placeholder="介绍显问 GEO 的核心价值" />
          </Form.Item>
        </Form>
      </Card>
      <Card className="admin-surface" title="注册与公告" style={{ marginTop: 18 }}>
        <Form layout="vertical" disabled>
          <Form.Item label="开放用户注册" name="registrationEnabled" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="平台公告" name="announcement">
            <Input.TextArea rows={4} placeholder="输入需要展示给用户的公告" />
          </Form.Item>
          <Form.Item label="基础平台文案" name="platformCopy">
            <Input.TextArea rows={4} placeholder="平台帮助信息与基础说明" />
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
