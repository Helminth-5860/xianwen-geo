import { AntdRegistry } from "@ant-design/nextjs-registry";
import type { Metadata } from "next";

import { UserAssistantWidget } from "@/components/assistant/user-assistant-widget";
import {
  SubjectWorkspaceProvider,
  SubjectWorkspaceTopbar,
} from "@/components/subject-workspace-context";
import { UserWorkspaceNavigation } from "@/components/user-workspace-navigation";

import "./globals.css";
import "./product-shell.css";
import "./xw-tokens.css";
import "./assistant-widget.css";
import "./website-audit.css";

export const metadata: Metadata = {
  title: "显问 GEO 智能体系统",
  description: "帮助企业提升在主流人工智能回答中的可见度与推荐表现",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>
          <SubjectWorkspaceProvider>
            <div className="geo-app-shell">
              <UserWorkspaceNavigation />
              <div className="geo-app-shell__content">
                <SubjectWorkspaceTopbar />
                {children}
              </div>
              <UserAssistantWidget />
            </div>
          </SubjectWorkspaceProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
